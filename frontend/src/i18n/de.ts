import type { Dictionary } from './ru'

/** Typed against the Russian dictionary: a missing key will not compile.
    Addresses the reader as "du" — it is a household app, and so is every
    German consumer app the family already uses. */
export const de: Dictionary = {
  locale: 'de-DE',

  app: {
    title: 'Sparschwein',
    offline:
      'Keine Verbindung — du siehst die zuletzt geladenen Daten. Änderungen werden nicht gespeichert.',
    noAccessHint:
      'Öffne die App über den Bot in Telegram — oder schick dem Bot /login, dann bekommst du einen Link für den Browser.',
    genericError: (status: number) => `Fehler ${status}`,
    loginNoToken: 'In diesem Link steht kein Anmeldecode. Fordere einen neuen an: /login an den Bot.',
  },

  tabs: {
    active: 'Aktiv',
    draft: 'Entwürfe',
    used: 'Verbraucht',
    archived: 'Archiv',
  },

  tabHints: {
    active: 'damit kannst du zahlen',
    draft: 'Foto da, Felder leer',
    used: 'da ist nichts mehr drauf',
    archived: 'weggeräumt, Restguthaben möglich',
  },

  status: {
    draft: 'Entwurf',
    active: 'Aktiv',
    used: 'Verbraucht',
    archived: 'Im Archiv',
  },

  list: {
    search: 'Suche: Laden, Notiz…',
    all: 'Alle',
    menu: 'Menü',
    add: 'Karte hinzufügen',
    stats: '📊 Statistik',
    statsHint: 'was da ist, wohin es geht, wer ausgibt',
    close: 'Schließen',
    inArchive: (amount: string) =>
      `💸 Im Archiv liegen noch ${amount} — vielleicht wurden die Karten zu früh weggeräumt`,
    shopSummary: (shop: string, cards: string, amount: string | null) =>
      `${shop}: ${cards}${amount ? ` · ${amount}` : ''}`,
    cards: (n: number) => `${n} ${n === 1 ? 'Karte' : 'Karten'}`,
    noResults: (query: string) => `Nichts gefunden${query ? ` für „${query}“` : ''}.`,
    resetFilters: 'Filter zurücksetzen',
    noBalance: 'unbefristet',
    unchecked: 'ungeprüft',
    spentOn: (date: string) => `verbraucht ${date}`,
    outOf: (amount: string) => `von ${amount}`,
    cardFallback: (id: number) => `Karte #${id}`,
  },

  empty: {
    active: 'Noch nichts da. Schick dem Bot ein Foto der Karte oder leg sie von Hand an.',
    draft: 'Keine Entwürfe. Schick dem Bot einen Screenshot, dann taucht er hier auf.',
    used: 'Bisher nichts verbraucht.',
    archived: 'Das Archiv ist leer.',
  },

  card: {
    scanHint: '📷 Tippen, um sie dem Scanner zu zeigen',
    discount: 'Rabatt',
    name: 'Name',
    expires: 'Gültig bis',
    expiresByRule: ' laut Ladenregel',
    validFrom: 'Gültig ab',
    conditions: 'Bedingungen',
    note: 'Notiz',
    addedBy: 'Hinzugefügt von',
    usedBy: 'Verbraucht von',
    copy: 'kopieren',
    copied: 'kopiert',
    copyFailed: 'Kopieren hat nicht geklappt — markiere den Code von Hand.',
    deleteConfirm: 'Karte mitsamt Foto und Historie löschen?',
  },

  actions: {
    activate: 'Aktiv setzen',
    useUp: '✅ Alles ausgegeben',
    markUsed: '✅ Verbraucht',
    unuse: 'Zurück auf aktiv',
    restore: 'Aus dem Archiv holen',
    archive: '📦 Ins Archiv',
    edit: '✏️ Bearbeiten',
    delete: 'Löschen',
  },

  balance: {
    rest: 'Restguthaben',
    update: 'Guthaben aktualisieren',
    uncertainBadge: '❔ Guthaben nicht bestätigt',
    markUncertain: 'Nicht sicher, ob noch Geld drauf ist',
    markCertain: 'Guthaben ist bestätigt',
    remaining: 'Rest',
    spent: 'Ausgegeben',
    amountSpent: 'Bezahlter Betrag',
    amountRemaining: 'Restguthaben laut Bon',
    note: 'Notiz: was gekauft wurde (optional)',
    save: 'Speichern',
    saving: 'Speichere…',
    cancel: 'Abbrechen',
  },

  scan: {
    photo: '🖼 Foto',
    code: '▮▮ Barcode',
    rotate: '↻ Drehen',
    done: 'Fertig',
    zoomIn: 'Vergrößern',
    zoomOut: 'Verkleinern',
    photoAlt: 'Karte zum Scannen',
    barcodeAlt: 'Barcode der Karte',
    hintPhoto:
      'Zoomen mit zwei Fingern oder Doppeltipp. Helligkeit hochdrehen: ein helles Display liest der Scanner zuverlässiger',
    hintBarcode:
      'Aus der Karte neu gezeichnet — scharf bei jedem Zoom. Wird nicht gelesen? Wechsle aufs Foto',
  },

  comments: {
    title: 'Kommentare',
    empty: 'Hier hat noch niemand etwas geschrieben.',
    placeholder: 'An die Familie schreiben…',
    delete: 'löschen',
    deleteConfirm: 'Kommentar löschen?',
  },

  history: {
    title: 'Historie',
    system: 'System',
  },

  form: {
    newTitle: 'Neue Karte',
    editTitle: 'Karte bearbeiten',
    addPhoto: '📷 Foto oder Screenshot hinzufügen',
    uploading: 'Lade hoch…',
    removePhoto: 'Foto entfernen',
    merchant: 'Laden',
    merchantPlaceholder: 'DM, Rewe, Lidl…',
    kind: 'Art',
    kindAmount: 'Betrag',
    kindPercent: 'Prozent',
    kindOther: 'Sonstiges',
    faceValue: 'Nennwert',
    percent: 'Prozent',
    currency: 'Währung',
    note: 'Notiz für die Familie',
    more: 'Mehr ▾',
    less: 'Weniger ▴',
    name: 'Name',
    namePlaceholder: 'falls anders als der Laden',
    code: 'Code',
    codePlaceholder: 'falls auf dem Foto nicht zu erkennen',
    validFrom: 'Gültig ab',
    validUntil: 'Gültig bis',
    conditions: 'Bedingungen',
    save: 'Speichern',
    saving: 'Speichere…',
    cancel: 'Abbrechen',
    noteHints: [
      'Finger weg! Die ist für den neuen Staubsauger',
      'Liegt im Handschuhfach unter den Mandarinen',
      'Wer sie ausgibt, schuldet mir einen Kaffee',
      'Versteckt hinter dem Glas mit den Linsen',
      'Nur für etwas Unnützes und Schönes',
      'Papa, das ist nicht für Werkzeug',
    ],
    conditionHints: [
      'ab 30 EUR und natürlich nicht auf Alkohol',
      'nicht auf Aktionsware — wie immer',
      'nicht kombinierbar, mit gar nichts',
      'nur dienstags, danke, Rewe',
      'einmal, eine Person, ein Markt',
    ],
  },

  stats: {
    title: 'Statistik',
    onCards: 'auf den Karten',
    activeCards: (n: number) => `${n} aktive ${n === 1 ? 'Karte' : 'Karten'}`,
    thisMonth: 'diesen Monat',
    allTime: 'insgesamt',
    sameAsLastMonth: 'wie im Vormonat',
    vsLastMonth: (delta: string) => `${delta} zum Vormonat`,
    atRisk: 'Geld in Gefahr',
    expired: '⚠️ auf abgelaufenen Karten',
    expiringIn: (days: number) => `⏳ läuft in ${days} Tagen ab`,
    inArchive: '📦 liegt im Archiv',
    uncertain: '❔ Guthaben nicht bestätigt',
    whereItGoes: 'Wohin es geht',
    whoSpends: 'Wer ausgibt',
    byMonth: 'Nach Monat',
    left: (amount: string) => `${amount} übrig`,
    purchases: (n: number) => `${n} ${n === 1 ? 'Einkauf' : 'Einkäufe'}`,
    nothingSpent: 'Bisher nichts ausgegeben.',
    tapColumn: 'Tippe auf eine Säule, um den Betrag zu sehen',
  },

  expiry: {
    expired: 'abgelaufen',
    lastDay: 'heute letzter Tag',
    days: (n: number) => `${n} ${n === 1 ? 'Tag' : 'Tage'}`,
    until: (date: string) => `bis ${date}`,
  },

  events: {
    created: 'hat die Karte angelegt',
    published: 'hat sie aktiv gesetzt',
    updated: 'hat geändert',
    balance_updated: 'hat das Guthaben aktualisiert',
    used: 'hat sie als verbraucht markiert',
    unused: 'hat sie zurück auf aktiv gesetzt',
    archived: 'hat sie ins Archiv gelegt',
    restored: 'hat sie aus dem Archiv geholt',
    commented: 'hat kommentiert',
    image_replaced: 'hat das Foto ersetzt',
    spentLeft: (spent: string, left: string, note: string) =>
      `hat ${spent} abgebucht, ${left} übrig${note}`,
    corrected: (left: string, note: string) => `hat das Guthaben korrigiert: ${left}${note}`,
  },

  // Read after "hat geändert:", so these are in the accusative.
  fields: {
    merchant: 'den Laden',
    title: 'den Namen',
    code: 'den Code',
    value_kind: 'die Art',
    value_amount: 'den Betrag',
    currency: 'die Währung',
    valid_from: 'den Beginn',
    valid_until: 'die Gültigkeit',
    conditions: 'die Bedingungen',
    notes: 'die Notiz',
    balance_uncertain: 'die Markierung „Guthaben nicht bestätigt“',
    balance_amount: 'das Guthaben',
  },

  common: {
    back: 'Zurück',
  },

  demo: {
    banner: 'Demo: alles erfunden, nichts wird gespeichert',
    exit: 'Verlassen',
    enter: 'Demo ansehen',
    enterHint: 'Erfundene Karten, aber alles funktioniert',
    you: 'Max',
    partner: 'Anna',
    errors: {
      spendTooMuch: (spent: string, current: string) =>
        `${spent} geht nicht — auf der Karte sind ${current}`,
      aboveFace: (face: string) => `Das Guthaben liegt über dem Nennwert (${face})`,
    },
    seed: {
      reweNote: 'zum Geburtstag geschenkt',
      groceries: 'Lebensmittel',
      weeklyShop: 'Wocheneinkauf',
      shampoo: 'Shampoo und Zahnpasta',
      candles: 'Kerzen und ein Bilderrahmen',
      jetComment: 'ziemlich sicher schon verbraucht — an der Kasse prüfen',
      totalComment: 'liegt im Handschuhfach',
      kauflandComment: 'läuft nächste Woche ab, lasst sie uns ausgeben',
      lidlComment: 'das war’s, leer',
      douglasConditions: 'ab 30 EUR',
    },
  },
}
