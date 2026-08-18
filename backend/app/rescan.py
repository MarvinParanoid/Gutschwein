"""Read the codes again out of pictures already uploaded: `python -m app.rescan`.

A voucher's barcode is decoded once, when its picture arrives, and never again —
so a card that the decoder could not read stays unreadable even after the decoder
learns to read it. That is not hypothetical: six gift certificates sat in the
database with no code at all until the panel search was written, and the picture
that would now decode was already on disk.

Nothing is overwritten. A code someone typed is the authority, exactly as it is on
upload, and a picture that still refuses is left alone rather than being cleared —
a rescan may only add what is missing.

    python -m app.rescan                # what would change, and nothing else
    python -m app.rescan --apply        # write it
    python -m app.rescan --all --apply  # try the ones that already have a format too
"""

import argparse
import asyncio

from sqlalchemy import select

from app import barcode, storage
from app.db import SessionLocal
from app.models import Voucher


async def rescan(apply: bool, everything: bool) -> None:
    async with SessionLocal() as session:
        query = select(Voucher).where(Voucher.image_path.is_not(None))
        if not everything:
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
            code = voucher.code or found.text[:128]
            kept = " (keeping the typed code)" if voucher.code else ""
            print(f"  {voucher.id:>4}  {voucher.merchant:<20} {found.format:<10} {code}{kept}")
            if apply:
                voucher.barcode_format = found.format
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
    args = parser.parse_args()
    asyncio.run(rescan(args.apply, args.everything))


if __name__ == "__main__":
    main()
