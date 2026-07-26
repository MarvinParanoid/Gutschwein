import type { Dictionary } from './ru'

/** Typed against the Russian dictionary: a missing key will not compile. */
export const en: Dictionary = {
  locale: 'en-GB',

  app: {
    title: 'Sparschwein',
    offline: 'No connection — showing the last loaded data. Changes will not be saved.',
    noAccessHint:
      'Open the app from the bot in Telegram — or send the bot /login and it will give you a link for the browser.',
    genericError: (status: number) => `Error ${status}`,
    loginNoToken: 'That link has no login code. Ask for a new one: send /login to the bot.',
  },

  tabs: {
    active: 'Active',
    draft: 'Drafts',
    used: 'Spent',
    archived: 'Archive',
  },

  tabHints: {
    active: 'something to pay with',
    draft: 'photo taken, fields empty',
    used: 'nothing left on them',
    archived: 'put away, money may still be on them',
  },

  status: {
    draft: 'Draft',
    active: 'Active',
    used: 'Spent',
    archived: 'Archived',
  },

  list: {
    search: 'Search: shop, note…',
    all: 'All',
    menu: 'Menu',
    add: 'Add a card',
    stats: '📊 Statistics',
    statsHint: 'what you have, where it goes, who spends',
    close: 'Close',
    inArchive: (amount: string) =>
      `💸 ${amount} still sits in the archive — maybe those cards were put away too early`,
    shopSummary: (shop: string, cards: string, amount: string | null) =>
      `${shop}: ${cards}${amount ? ` · ${amount}` : ''}`,
    cards: (n: number) => `${n} ${n === 1 ? 'card' : 'cards'}`,
    noResults: (query: string) => `Nothing found${query ? ` for “${query}”` : ''}.`,
    resetFilters: 'Clear filters',
    noBalance: 'no expiry',
    unchecked: 'not checked',
    spentOn: (date: string) => `spent ${date}`,
    outOf: (amount: string) => `of ${amount}`,
    cardFallback: (id: number) => `Card #${id}`,
  },

  empty: {
    active: 'Nothing here yet. Send the bot a photo of a card, or add one by hand.',
    draft: 'No drafts. Send the bot a screenshot and it will show up here.',
    used: 'Nothing spent yet.',
    archived: 'The archive is empty.',
  },

  card: {
    scanHint: '📷 Tap to show it to the scanner',
    discount: 'Discount',
    name: 'Name',
    expires: 'Expires',
    expiresByRule: ' by the shop’s rule',
    validFrom: 'Valid from',
    conditions: 'Conditions',
    note: 'Note',
    addedBy: 'Added by',
    usedBy: 'Spent by',
    copy: 'copy',
    copied: 'copied',
    copyFailed: 'Could not copy — select the code by hand.',
    deleteConfirm: 'Delete this card along with its photo and history?',
  },

  actions: {
    activate: 'Make active',
    useUp: '✅ Spent it all',
    markUsed: '✅ Used',
    unuse: 'Back to active',
    restore: 'Out of the archive',
    archive: '📦 Archive',
    edit: '✏️ Edit',
    delete: 'Delete',
  },

  balance: {
    rest: 'balance',
    update: 'Update balance',
    uncertainBadge: '❔ balance not confirmed',
    markUncertain: 'Not sure any money is left',
    markCertain: 'Balance is confirmed',
    remaining: 'Left',
    spent: 'Spent',
    amountSpent: 'Amount paid',
    amountRemaining: 'Balance from the receipt',
    note: 'Note: what you bought (optional)',
    save: 'Save',
    saving: 'Saving…',
    cancel: 'Cancel',
  },

  scan: {
    photo: '🖼 Photo',
    code: '▮▮ Barcode',
    rotate: '↻ Rotate',
    done: 'Done',
    zoomIn: 'Zoom in',
    zoomOut: 'Zoom out',
    photoAlt: 'Card for scanning',
    barcodeAlt: 'Card barcode',
    hintPhoto:
      'Pinch or double-tap to zoom. Turn the brightness up: scanners read a bright screen better',
    hintBarcode:
      'Redrawn from the card — sharp at any zoom. Not scanning? Switch to the photo',
  },

  comments: {
    title: 'Comments',
    empty: 'Nobody has written anything yet.',
    placeholder: 'Write to the family…',
    delete: 'delete',
    deleteConfirm: 'Delete this comment?',
  },

  history: {
    title: 'History',
    system: 'System',
  },

  form: {
    newTitle: 'New card',
    editTitle: 'Edit card',
    addPhoto: '📷 Add a photo or screenshot',
    uploading: 'Uploading…',
    removePhoto: 'remove photo',
    merchant: 'Shop',
    merchantPlaceholder: 'DM, Rewe, Lidl…',
    kind: 'Type',
    kindAmount: 'Amount',
    kindPercent: 'Percent',
    kindOther: 'Other',
    faceValue: 'Face value',
    percent: 'Percent',
    currency: 'Currency',
    note: 'Note for the family',
    more: 'More ▾',
    less: 'Less ▴',
    name: 'Name',
    namePlaceholder: 'if different from the shop',
    code: 'Code',
    codePlaceholder: 'if the photo does not show it',
    validFrom: 'Valid from',
    validUntil: 'Valid until',
    conditions: 'Conditions',
    save: 'Save',
    saving: 'Saving…',
    cancel: 'Cancel',
    noteHints: [
      'Hands off! This one is for the new vacuum',
      'In the glovebox, under the tangerines',
      'Spend it and you owe me a coffee',
      'Hidden behind the jar of buckwheat',
      'Only for something useless and lovely',
      'Dad, this is not for tools',
    ],
    conditionHints: [
      'from 30 EUR, and not on alcohol of course',
      'not on sale items — as always',
      'combines with absolutely nothing',
      'Tuesdays only, thanks Rewe',
      'once, one person, one shop',
    ],
  },

  stats: {
    title: 'Statistics',
    onCards: 'on the cards',
    activeCards: (n: number) => `${n} active ${n === 1 ? 'card' : 'cards'}`,
    thisMonth: 'this month',
    allTime: 'all time',
    sameAsLastMonth: 'same as last month',
    vsLastMonth: (delta: string) => `${delta} vs last month`,
    atRisk: 'Money at risk',
    expired: '⚠️ on expired cards',
    expiringIn: (days: number) => `⏳ expiring within ${days} days`,
    inArchive: '📦 sitting in the archive',
    uncertain: '❔ balance not confirmed',
    whereItGoes: 'Where it goes',
    whoSpends: 'Who spends',
    byMonth: 'By month',
    left: (amount: string) => `${amount} left`,
    purchases: (n: number) => `${n} ${n === 1 ? 'purchase' : 'purchases'}`,
    nothingSpent: 'Nothing spent yet.',
    tapColumn: 'Tap a column to see the amount',
  },

  expiry: {
    expired: 'expired',
    lastDay: 'last day today',
    days: (n: number) => `${n} ${n === 1 ? 'day' : 'days'}`,
    until: (date: string) => `until ${date}`,
  },

  events: {
    created: 'added the card',
    published: 'made it active',
    updated: 'changed',
    balance_updated: 'updated the balance',
    used: 'marked it used',
    unused: 'put it back to active',
    archived: 'archived it',
    restored: 'took it out of the archive',
    commented: 'left a comment',
    image_replaced: 'replaced the photo',
    spentLeft: (spent: string, left: string, note: string) =>
      `spent ${spent}, ${left} left${note}`,
    corrected: (left: string, note: string) => `corrected the balance: ${left}${note}`,
  },

  fields: {
    merchant: 'the shop',
    title: 'the name',
    code: 'the code',
    value_kind: 'the type',
    value_amount: 'the amount',
    currency: 'the currency',
    valid_from: 'the start date',
    valid_until: 'the expiry',
    conditions: 'the conditions',
    notes: 'the note',
    balance_uncertain: 'the “balance not confirmed” mark',
    balance_amount: 'the balance',
  },

  common: {
    back: 'Back',
  },

  demo: {
    banner: 'Demo: the cards are made up and nothing is saved',
    exit: 'Leave',
    enter: 'Try the demo',
    enterHint: 'Made-up cards, but everything works',
    you: 'You',
    partner: 'Anna',
    errors: {
      spendTooMuch: (spent: string, current: string) =>
        `Cannot spend ${spent} — the card holds ${current}`,
      aboveFace: (face: string) => `The balance exceeds the face value (${face})`,
    },
    seed: {
      reweNote: 'a birthday present',
      groceries: 'groceries',
      weeklyShop: 'the weekly shop',
      shampoo: 'shampoo and toothpaste',
      candles: 'candles and a frame',
      jetComment: 'pretty sure this one is spent — check at the till',
      totalComment: 'in the glovebox',
      kauflandComment: 'burns in a week, let us spend it',
      lidlComment: 'that is it, empty',
      douglasConditions: 'from 30 EUR',
    },
  },
}
