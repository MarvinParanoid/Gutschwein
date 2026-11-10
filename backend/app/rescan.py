"""Read the codes again out of pictures already uploaded: `python -m app.rescan`.

A voucher's barcode is decoded once, when its picture arrives, and never again —
so a card that the decoder could not read stays unreadable even after the decoder
learns to read it. That is not hypothetical: six gift certificates sat in the
database with no code at all until the panel search was written, and the picture
that would now decode was already on disk.

Nothing is overwritten. A code someone typed is the authority, exactly as it is on
upload, and a picture that still refuses is left alone rather than being cleared —
a rescan may only add what is missing. The one exception has to be asked for: with
`--repair`, a card whose stored code and format cannot be drawn at all takes the
picture's reading instead. That pair is nobody's intent — it is how an older version
left a card whose picture was replaced while the old code stayed, and until it is
mended the till has no bars to show.

    python -m app.rescan                # what would change, and nothing else
    python -m app.rescan --apply        # write it
    python -m app.rescan --all --apply  # try the ones that already have a format too
    python -m app.rescan --repair --apply   # …and mend pairs that cannot be drawn
"""

import argparse
import asyncio

from sqlalchemy import select

from app import barcode, storage
from app.db import SessionLocal
from app.models import Voucher


def _drawable(code: str | None, barcode_format: str | None) -> bool:
    """Whether the pair draws at all: something to see, and a format that can carry it."""
    if not code or not barcode_format:
        return False
    return barcode.problem(code, barcode_format) is None


def decide(voucher: Voucher, found: barcode.Decoded, repair: bool) -> tuple[str, str | None, str]:
    """The code and format the card should have, and a note for the printed line.

    What is missing is filled from the picture. What is there and draws is somebody's
    word and stays as it is — a picture may dress a bare code in bars, but only in
    bars that fit it. With `repair`, a stored pair that cannot be drawn is treated as
    nobody's word: the picture is what is left that makes sense of the card.
    """
    decoded = found.text[:128]
    if not voucher.code:
        return decoded, found.format, ""
    if not voucher.barcode_format:
        draws = barcode.problem(voucher.code, found.format) is None
        return voucher.code, found.format if draws else None, ""
    if repair and not _drawable(voucher.code, voucher.barcode_format) and _drawable(
        decoded, found.format
    ):
        return decoded, found.format, "  (re-read from the picture: the stored pair did not draw)"
    return voucher.code, voucher.barcode_format, " (keeping the typed code)"


async def rescan(apply: bool, everything: bool, repair: bool = False) -> None:
    async with SessionLocal() as session:
        query = select(Voucher).where(Voucher.image_path.is_not(None))
        if not (everything or repair):
            query = query.where(Voucher.barcode_format.is_(None))
        vouchers = (await session.execute(query.order_by(Voucher.id))).scalars().all()

        missing = read = failed = 0
        for voucher in vouchers:
            path = storage.absolute_path(voucher.image_path or "")
            if not path.is_file():
                missing += 1
                print(f"  {voucher.id:>4}  {voucher.merchant:<20} picture gone")
                continue

            # Decoding is CPU-bound and this walks the whole table, so it stays off
            # the loop even here, where nothing else is waiting on it.
            found = await asyncio.to_thread(barcode.decode, path.read_bytes())
            if found is None:
                failed += 1
                print(f"  {voucher.id:>4}  {voucher.merchant:<20} still unreadable")
                continue

            read += 1
            code, fmt, note = decide(voucher, found, repair)
            print(f"  {voucher.id:>4}  {voucher.merchant:<20} {fmt or '':<10} {code}{note}")
            if apply:
                voucher.barcode_format = fmt
                voucher.code = code

        if apply:
            await session.commit()

        print(
            f"\n{len(vouchers)} looked at, {read} decoded, {failed} still unreadable, "
            f"{missing} without a file"
        )
        if read and not apply:
            print("nothing was written — repeat with --apply")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.rescan", description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the results")
    parser.add_argument(
        "--all",
        dest="everything",
        action="store_true",
        help="include vouchers whose barcode was already decoded",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="also re-read cards whose stored code and format cannot be drawn",
    )
    args = parser.parse_args()
    asyncio.run(rescan(args.apply, args.everything, args.repair))


if __name__ == "__main__":
    main()
