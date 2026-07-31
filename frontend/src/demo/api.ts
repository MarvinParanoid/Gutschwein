/**
 * The API client used in demo mode: the same surface as the HTTP one, answered
 * from an object in this tab.
 *
 * It reimplements the server's rules rather than faking screens — spending
 * writes a balance event, emptying a card marks it used, statistics are summed
 * from the event log — so what a visitor tries out is what the real thing does.
 * Nothing here touches the network.
 */

import type { ApiClient } from "../api";
import { trimAmount } from "../format";
import { t } from "../i18n";
import type {
  Comment,
  EventKind,
  Stats,
  User,
  Voucher,
  VoucherDraft,
  VoucherStatus,
} from "../types";
import { blankVoucher, createSeed, PARTNER, YOU, type DemoState } from "./seed";

const MONTHS_BACK = 6;
const TOP_MERCHANTS = 8;
const EXPIRING_SOON_DAYS = 30;
/** What most German retailers do; enough of the rule to demonstrate the "≈". */
const DEFAULT_EXPIRY_YEARS = 3;
/** Where a card saved without a currency belongs, same as on the server. */
const FALLBACK_CURRENCY = "EUR";

const cents = (amount: string | null | undefined) =>
  Math.round(Number(amount ?? 0) * 100);
const money = (value: number) => (value / 100).toFixed(2);
/** Balances of a set of cards, one entry per currency and none for the empty ones. */
const byCurrency = (vouchers: Voucher[]) => {
  const totals = new Map<string, number>();
  for (const voucher of vouchers) {
    const code = voucher.currency || FALLBACK_CURRENCY;
    totals.set(code, (totals.get(code) ?? 0) + cents(voucher.balance_amount));
  }
  return [...totals.entries()]
    .filter(([, amount]) => amount > 0)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([currency, amount]) => ({ amount: money(amount), currency }));
};
const now = () => new Date().toISOString();
const today = () => new Date(new Date().toISOString().slice(0, 10));

function fail(message: string): never {
  throw new Error(message);
}

/** days_left and is_expired are derived on the server; here too, on every read. */
function derive(voucher: Voucher): Voucher {
  if (!voucher.valid_until)
    return { ...voucher, days_left: null, is_expired: false };
  const left = Math.round(
    (Date.parse(voucher.valid_until) - today().getTime()) / 86_400_000,
  );
  return { ...voucher, days_left: left, is_expired: left < 0 };
}

function matches(voucher: Voucher, query: string): boolean {
  const needle = query.trim().toLowerCase();
  return [
    voucher.merchant,
    voucher.title,
    voucher.code,
    voucher.conditions,
    voucher.notes,
  ]
    .join("\n")
    .toLowerCase()
    .includes(needle);
}

const monthKey = (iso: string) => iso.slice(0, 7);

function shiftMonth(offset: number): string {
  const date = today();
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() + offset);
  return date.toISOString().slice(0, 7);
}

export function createDemoApi(): ApiClient {
  // Owned by the client, not the module: a factory that quietly shared one
  // dataset between its instances would be a trap for the next caller.
  const state: DemoState = createSeed();

  function find(id: number): Voucher {
    const voucher = state.vouchers.find((v) => v.id === id);
    if (!voucher) fail(t.app.genericError(404));
    return voucher;
  }

  function record(
    voucher: Voucher,
    kind: EventKind,
    payload: Record<string, unknown> = {},
    actor: User | null = YOU,
  ): void {
    state.events.push({
      id: state.events.length + 1,
      voucher_id: voucher.id,
      kind,
      payload,
      actor,
      created_at: now(),
    });
    voucher.updated_at = now();
  }

  function markUsed(voucher: Voucher): void {
    voucher.status = "used";
    voucher.used_at = now();
    voucher.used_by = YOU;
  }

  return {
    login: async () => YOU,
    logout: async () => undefined,
    me: async () => ({ user: YOU, members: [YOU, PARTNER] }),

    sessions: async () => state.sessions,
    revokeSession: async (id) => {
      if (state.sessions.find((s) => s.id === id)?.current) fail(t.app.genericError(400))
      state.sessions = state.sessions.filter((s) => s.id !== id)
    },
    revokeOtherSessions: async () => {
      state.sessions = state.sessions.filter((s) => s.current)
    },
    invite: async (name = '') => ({
      // A link shaped like the real one, on this very page, so the screen can be
      // tried out; the token behind it means nothing.
      url: `${location.origin}/login#demo-${Math.random().toString(36).slice(2, 14)}`,
      minutes: 10,
      member: name.trim() || YOU.display_name,
    }),

    listVouchers: async (status, q, merchant) => {
      let found = state.vouchers.filter(
        (v) => status === "all" || v.status === status,
      );
      if (merchant) found = found.filter((v) => v.merchant === merchant);
      if (q?.trim()) found = found.filter((v) => matches(v, q));

      const byExpiry = status === "active" || status === "all";
      return [...found]
        .sort((a, b) => {
          if (byExpiry && a.valid_until !== b.valid_until) {
            // Soonest deadline first; a card without one sinks to the bottom.
            if (!a.valid_until) return 1;
            if (!b.valid_until) return -1;
            return a.valid_until < b.valid_until ? -1 : 1;
          }
          const key = byExpiry ? "created_at" : "updated_at";
          return a[key] < b[key] ? 1 : -1;
        })
        .map(derive);
    },

    getVoucher: async (id) => derive(find(id)),

    merchants: async () =>
      [
        ...new Set(state.vouchers.map((v) => v.merchant).filter(Boolean)),
      ].sort(),

    counts: async () => {
      const of = (status: VoucherStatus) =>
        state.vouchers.filter((v) => v.status === status);
      return {
        active: of("active").length,
        draft: of("draft").length,
        used: of("used").length,
        archived: of("archived").length,
        archived_balance: byCurrency(of("archived")),
      };
    },

    merchantStats: async (status) => {
      const uses = new Map<string, number>();
      for (const event of state.events) {
        if (event.kind !== "balance_updated") continue;
        const shop = state.vouchers.find(
          (v) => v.id === event.voucher_id,
        )?.merchant;
        if (shop) uses.set(shop, (uses.get(shop) ?? 0) + 1);
      }

      const shops = new Map<
        string,
        { count: number; balance: number; currency: string }
      >();
      for (const voucher of state.vouchers) {
        if (!voucher.merchant) continue;
        if (status !== "all" && voucher.status !== status) continue;
        const currency = voucher.currency || FALLBACK_CURRENCY;
        const entry = shops.get(voucher.merchant) ?? {
          count: 0,
          balance: 0,
          currency,
        };
        entry.count += 1;
        // One chip holds one sum. A shop with cards in two currencies has no
        // honest single amount, so it shows none.
        if (entry.currency === currency) entry.balance += cents(voucher.balance_amount);
        else {
          entry.currency = "";
          entry.balance = 0;
        }
        shops.set(voucher.merchant, entry);
      }

      return (
        [...shops.entries()]
          .map(([merchant, { count, balance, currency }]) => ({
            merchant,
            count,
            balance: money(balance),
            currency,
            uses: uses.get(merchant) ?? 0,
          }))
          // Regulars float up; one-off shops sink to the end of the row.
          .sort(
            (a, b) =>
              b.uses - a.uses ||
              b.count - a.count ||
              a.merchant.toLowerCase().localeCompare(b.merchant.toLowerCase()),
          )
      );
    },

    stats: async () => buildStats(state),

    createVoucher: async (draft: VoucherDraft) => {
      const { status = "active", ...fields } = draft;
      const voucher = blankVoucher(state.nextId++, {
        ...fields,
        status,
        created_at: now(),
        updated_at: now(),
      });
      if (voucher.value_kind === "amount")
        voucher.balance_amount = voucher.value_amount;
      // Most cards print no date, only a shop rule. Three years is the common
      // one; the app says "≈" so the guess never reads as printed fact.
      if (
        !voucher.valid_until &&
        voucher.merchant &&
        voucher.value_kind === "amount"
      ) {
        const guess = today();
        guess.setUTCFullYear(guess.getUTCFullYear() + DEFAULT_EXPIRY_YEARS);
        voucher.valid_until = guess.toISOString().slice(0, 10);
        voucher.expiry_estimated = true;
      }
      state.vouchers.push(voucher);
      record(voucher, "created");
      return derive(voucher);
    },

    updateVoucher: async (id, patch) => {
      const voucher = find(id);
      const changed: string[] = [];
      const previousValue = voucher.value_amount;

      for (const [field, value] of Object.entries(patch) as [
        keyof VoucherDraft,
        never,
      ][]) {
        if (field === "status") continue;
        if (voucher[field as keyof Voucher] !== value) {
          Object.assign(voucher, { [field]: value });
          changed.push(field);
        }
      }
      // Correcting the face value of an untouched card moves the balance with it.
      if (
        changed.includes("value_amount") &&
        voucher.value_kind === "amount" &&
        cents(previousValue) === cents(voucher.balance_amount)
      ) {
        voucher.balance_amount = voucher.value_amount;
      }
      if (changed.length) record(voucher, "updated", { fields: changed });
      voucher.updated_at = now();
      return derive(voucher);
    },

    deleteVoucher: async (id) => {
      state.vouchers = state.vouchers.filter((v) => v.id !== id);
      state.comments = state.comments.filter((c) => c.voucher_id !== id);
      state.events = state.events.filter((e) => e.voucher_id !== id);
    },

    transition: async (id, action) => {
      const voucher = find(id);
      if (action === "use") {
        if (voucher.status === "used") fail("used");
        if (cents(voucher.balance_amount) > 0) {
          record(voucher, "balance_updated", {
            spent: voucher.balance_amount,
            remaining: "0",
            note: "",
          });
          voucher.balance_amount = "0.00";
        }
        markUsed(voucher);
        record(voucher, "used");
      } else if (action === "unuse") {
        voucher.status = "active";
        voucher.used_at = null;
        voucher.used_by = null;
        record(voucher, "unused");
      } else if (action === "archive") {
        voucher.status = "archived";
        record(voucher, "archived");
      } else if (action === "restore") {
        voucher.status = "active";
        record(voucher, "restored");
      } else {
        voucher.status = "active";
        record(voucher, "published");
      }
      return derive(voucher);
    },

    updateBalance: async (id, body) => {
      const voucher = find(id);
      if (voucher.value_kind !== "amount") fail(t.app.genericError(400));
      const current = cents(voucher.balance_amount ?? voucher.value_amount);
      const withCurrency = (value: number) =>
        `${trimAmount(money(value))} ${voucher.currency}`;

      let next: number;
      if (body.spent !== undefined) {
        const spent = cents(body.spent);
        if (spent > current) {
          fail(
            t.demo.errors.spendTooMuch(
              trimAmount(money(spent)),
              withCurrency(current),
            ),
          );
        }
        next = current - spent;
      } else {
        next = cents(body.remaining);
        const face = cents(voucher.value_amount);
        if (face > 0 && next > face)
          fail(t.demo.errors.aboveFace(withCurrency(face)));
      }

      const delta = current - next;
      voucher.balance_amount = money(next);
      // You just read the number off a receipt, so the doubt is settled.
      voucher.balance_uncertain = false;
      record(voucher, "balance_updated", {
        spent: money(delta),
        remaining: money(next),
        note: body.note ?? "",
      });
      if (next === 0 && voucher.status !== "used") {
        markUsed(voucher);
        record(voucher, "used", { reason: "balance_empty" });
      }
      return derive(voucher);
    },

    comments: async (id) =>
      state.comments
        .filter((c) => c.voucher_id === id)
        .map(
          ({ voucher_id: _ignored, ...comment }) => comment satisfies Comment,
        ),

    addComment: async (id, text) => {
      const voucher = find(id);
      const comment = {
        id: state.comments.length + 1,
        voucher_id: id,
        text,
        author: YOU,
        created_at: now(),
      };
      state.comments.push(comment);
      voucher.comments_count += 1;
      return comment;
    },

    deleteComment: async (voucherId, commentId) => {
      state.comments = state.comments.filter((c) => c.id !== commentId);
      find(voucherId).comments_count = state.comments.filter(
        (c) => c.voucher_id === voucherId,
      ).length;
    },

    events: async (id) =>
      state.events
        .filter((e) => e.voucher_id === id)
        // Newest first, with the id breaking ties: two events can share a second.
        .sort((a, b) =>
          a.created_at === b.created_at
            ? b.id - a.id
            : a.created_at < b.created_at
              ? 1
              : -1,
        )
        .map(({ voucher_id: _ignored, ...event }) => event),

    // The photo never leaves the page either: it becomes a data URI that the
    // image URL helper hands straight back to the <img>.
    uploadImage: (file) =>
      new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error("read failed"));
        reader.readAsDataURL(file);
      }),
  };
}

/** Every figure of one currency, while it is still being counted in cents. */
interface Bucket {
  cards: number;
  onCards: number;
  cardsActive: number;
  uncertain: number;
  cardsUncertain: number;
  expiring: number;
  expired: number;
  archived: number;
  spentTotal: number;
  onCardsByShop: Map<string, number>;
  byShop: Map<string, number>;
  byMember: Map<string, { spent: number; payments: number }>;
  byMonth: Map<string, number>;
}

/**
 * The statistics, grouped by currency exactly as the server groups them.
 *
 * Nothing is added across currencies and nothing is converted: a złoty card buys
 * nothing at a euro shop, so a single total would be a number the family does not
 * have. The demo lets you type any currency in the form, so this is reachable here
 * too, not only in a real installation.
 */
function buildStats(state: DemoState): Stats {
  const soon = new Date(today().getTime() + EXPIRING_SOON_DAYS * 86_400_000)
    .toISOString()
    .slice(0, 10);
  const startOfToday = today().toISOString().slice(0, 10);

  const buckets = new Map<string, Bucket>();
  const bucketFor = (currency: string): Bucket => {
    const code = currency || FALLBACK_CURRENCY;
    let bucket = buckets.get(code);
    if (!bucket) {
      bucket = {
        cards: 0,
        onCards: 0,
        cardsActive: 0,
        uncertain: 0,
        cardsUncertain: 0,
        expiring: 0,
        expired: 0,
        archived: 0,
        spentTotal: 0,
        onCardsByShop: new Map(),
        byShop: new Map(),
        byMember: new Map(),
        byMonth: new Map(),
      };
      buckets.set(code, bucket);
    }
    return bucket;
  };

  for (const voucher of state.vouchers) {
    const bucket = bucketFor(voucher.currency);
    bucket.cards += 1;
    const amount = cents(voucher.balance_amount);
    if (voucher.status === "archived") bucket.archived += amount;
    if (voucher.status !== "active") continue;

    bucket.cardsActive += 1;
    if (voucher.balance_uncertain) {
      // Money you are unsure about is not money you can plan with: it gets its
      // own line instead of joining the total.
      bucket.uncertain += amount;
      bucket.cardsUncertain += 1;
      continue;
    }
    bucket.onCards += amount;
    if (voucher.merchant) {
      bucket.onCardsByShop.set(
        voucher.merchant,
        (bucket.onCardsByShop.get(voucher.merchant) ?? 0) + amount,
      );
    }
    if (voucher.valid_until && amount > 0) {
      if (voucher.valid_until < startOfToday) bucket.expired += amount;
      else if (voucher.valid_until <= soon) bucket.expiring += amount;
    }
  }

  for (const event of state.events) {
    if (event.kind !== "balance_updated") continue;
    const amount = cents(String(event.payload.spent ?? "0"));
    if (amount <= 0) continue;
    const voucher = state.vouchers.find((v) => v.id === event.voucher_id);
    if (!voucher) continue;
    const bucket = bucketFor(voucher.currency);
    bucket.spentTotal += amount;

    const month = monthKey(event.created_at);
    bucket.byMonth.set(month, (bucket.byMonth.get(month) ?? 0) + amount);

    if (voucher.merchant) {
      bucket.byShop.set(
        voucher.merchant,
        (bucket.byShop.get(voucher.merchant) ?? 0) + amount,
      );
    }

    const name = event.actor?.display_name ?? YOU.display_name;
    const member = bucket.byMember.get(name) ?? { spent: 0, payments: 0 };
    member.spent += amount;
    member.payments += 1;
    bucket.byMember.set(name, member);
  }

  // No cards at all still opens the screen, and an empty page says nothing.
  if (buckets.size === 0) bucketFor(FALLBACK_CURRENCY);

  return {
    expiring_soon_days: EXPIRING_SOON_DAYS,
    // Busiest currency first, by card count — ordering by amount would be the
    // cross-currency comparison this split refuses to make.
    currencies: [...buckets.entries()]
      .sort(([left, a], [right, b]) => b.cards - a.cards || left.localeCompare(right))
      .map(([currency, bucket]) => {
        const shops = new Set([
          ...bucket.byShop.keys(),
          ...bucket.onCardsByShop.keys(),
        ]);
        return {
          currency,
          on_cards: money(bucket.onCards),
          cards_active: bucket.cardsActive,
          uncertain_balance: money(bucket.uncertain),
          cards_uncertain: bucket.cardsUncertain,
          expiring_soon: money(bucket.expiring),
          expired_balance: money(bucket.expired),
          archived_balance: money(bucket.archived),
          spent_total: money(bucket.spentTotal),
          spent_this_month: money(bucket.byMonth.get(shiftMonth(0)) ?? 0),
          spent_prev_month: money(bucket.byMonth.get(shiftMonth(-1)) ?? 0),
          by_merchant: [...shops]
            .map((merchant) => ({
              merchant,
              spent: money(bucket.byShop.get(merchant) ?? 0),
              on_cards: money(bucket.onCardsByShop.get(merchant) ?? 0),
            }))
            .sort(
              (a, b) =>
                Number(b.spent) - Number(a.spent) ||
                Number(b.on_cards) - Number(a.on_cards) ||
                a.merchant.localeCompare(b.merchant),
            )
            .slice(0, TOP_MERCHANTS),
          by_member: [...bucket.byMember.entries()]
            .map(([name, { spent, payments }]) => ({
              name,
              spent: money(spent),
              payments,
            }))
            .sort((a, b) => Number(b.spent) - Number(a.spent)),
          // A continuous axis: a month with no spending has to render as zero
          // rather than disappear.
          monthly: Array.from({ length: MONTHS_BACK }, (_, index) => {
            const month = shiftMonth(index - (MONTHS_BACK - 1));
            return { month, spent: money(bucket.byMonth.get(month) ?? 0) };
          }),
        };
      }),
  };
}
