/** Russian is the source of truth: every other locale must match this shape.
    Deliberately not `as const` — literal types would make every English
    string a type error instead of a translation. */
export const ru = {
  locale: 'ru-RU',

  app: {
    title: 'Sparschwein',
    offline: 'Нет сети — показываю последние загруженные данные. Изменения не сохранятся.',
    noAccessHint:
      'Откройте приложение через бота в Telegram — или пришлите боту команду /login, он даст ссылку для входа в браузере.',
    genericError: (status: number) => `Ошибка ${status}`,
    loginNoToken: 'В ссылке нет кода входа. Запросите новую: команда /login боту.',
  },

  tabs: {
    active: 'Активные',
    draft: 'Черновики',
    used: 'Использованные',
    archived: 'Архив',
  },

  tabHints: {
    active: 'есть чем платить',
    draft: 'фото есть, поля не заполнены',
    used: 'денег на них не осталось',
    archived: 'убраны с глаз, деньги могли остаться',
  },

  status: {
    draft: 'Черновик',
    active: 'Активный',
    used: 'Использован',
    archived: 'В архиве',
  },

  list: {
    search: 'Поиск: магазин, заметка…',
    all: 'Все',
    menu: 'Меню',
    add: 'Добавить купон',
    stats: '📊 Статистика',
    statsHint: 'сколько лежит, куда уходит, кто тратит',
    close: 'Закрыть',
    inArchive: (amount: string) =>
      `💸 В архиве ещё ${amount} — возможно, эти карты рано убрали`,
    shopSummary: (shop: string, cards: string, amount: string | null) =>
      `${shop}: ${cards}${amount ? ` · ${amount}` : ''}`,
    cards: (n: number) => `${n} ${plural(n, 'карта', 'карты', 'карт')}`,
    noResults: (query: string) =>
      `Ничего не нашлось${query ? ` по запросу «${query}»` : ''}.`,
    resetFilters: 'Сбросить фильтры',
    noBalance: 'без срока',
    unchecked: 'не проверен',
    spentOn: (date: string) => `потрачен ${date}`,
    outOf: (amount: string) => `из ${amount}`,
    cardFallback: (id: number) => `Купон #${id}`,
  },

  empty: {
    active: 'Пока пусто. Пришлите фото купона боту или добавьте вручную.',
    draft: 'Черновиков нет. Отправьте боту скрин — он появится здесь.',
    used: 'Ничего пока не потрачено.',
    archived: 'Архив пуст.',
  },

  card: {
    scanHint: '📷 Нажмите, чтобы показать сканеру',
    discount: 'Скидка',
    name: 'Название',
    expires: 'Срок',
    expiresByRule: ' по правилу магазина',
    validFrom: 'Действует с',
    conditions: 'Условия',
    note: 'Заметка',
    addedBy: 'Добавил',
    usedBy: 'Использовал',
    copy: 'копировать',
    copied: 'скопировано',
    copyFailed: 'Не удалось скопировать — выделите код вручную.',
    deleteConfirm: 'Удалить купон вместе с фото и историей?',
  },

  actions: {
    activate: 'В активные',
    useUp: '✅ Потратил всё',
    markUsed: '✅ Использован',
    unuse: 'Вернуть в активные',
    restore: 'Достать из архива',
    archive: '📦 В архив',
    edit: '✏️ Изменить',
    delete: 'Удалить',
  },

  balance: {
    rest: 'остаток',
    update: 'Обновить остаток',
    uncertainBadge: '❔ остаток не подтверждён',
    markUncertain: 'Не уверен, что деньги остались',
    markCertain: 'Остаток известен точно',
    remaining: 'Осталось',
    spent: 'Потратил',
    amountSpent: 'Сумма покупки',
    amountRemaining: 'Остаток с чека',
    note: 'Заметка: что купили (необязательно)',
    save: 'Сохранить',
    saving: 'Сохраняю…',
    cancel: 'Отмена',
  },

  scan: {
    photo: '🖼 Фото',
    code: '▮▮ Код',
    rotate: '↻ Повернуть',
    done: 'Готово',
    zoomIn: 'Увеличить',
    zoomOut: 'Уменьшить',
    photoAlt: 'Купон для сканирования',
    barcodeAlt: 'Штрихкод карты',
    hintPhoto:
      'Щипок или двойной тап — увеличить. Выкрутите яркость: так сканер читает надёжнее',
    hintBarcode:
      'Код перерисован из карты — чёткий на любом увеличении. Не читается? Переключитесь на фото',
  },

  comments: {
    title: 'Комментарии',
    empty: 'Пока никто ничего не написал.',
    placeholder: 'Написать семье…',
    delete: 'удалить',
    deleteConfirm: 'Удалить комментарий?',
  },

  history: {
    title: 'История',
    system: 'Система',
  },

  form: {
    newTitle: 'Новый купон',
    editTitle: 'Изменить купон',
    addPhoto: '📷 Добавить фото или скрин',
    uploading: 'Загружаю…',
    removePhoto: 'убрать фото',
    merchant: 'Магазин',
    merchantPlaceholder: 'DM, Rewe, Lidl…',
    kind: 'Тип скидки',
    kindAmount: 'На сумму',
    kindPercent: 'Процент',
    kindOther: 'Другое',
    faceValue: 'Номинал',
    percent: 'Процент',
    currency: 'Валюта',
    note: 'Заметка для семьи',
    more: 'Дополнительно ▾',
    less: 'Свернуть ▴',
    name: 'Название',
    namePlaceholder: 'если отличается от магазина',
    code: 'Код',
    codePlaceholder: 'если на фото его не видно',
    validFrom: 'Действует с',
    validUntil: 'Действует до',
    conditions: 'Условия',
    save: 'Сохранить',
    saving: 'Сохраняю…',
    cancel: 'Отмена',
    noteHints: [
      'Не трогать! Это на новый пылесос',
      'Лежит в бардачке под мандаринами',
      'Потратишь — купи мне кофе',
      'Спрятан за банкой с гречкой',
      'Только на что-нибудь бесполезное и приятное',
      'Папа, это не на инструменты',
    ],
    conditionHints: [
      'от 30 EUR и, конечно, не на алкоголь',
      'кроме акционных товаров — как всегда',
      'не суммируется ни с чем на свете',
      'только по вторникам, спасибо, Rewe',
      'один раз, одному человеку, в одном магазине',
    ],
  },

  stats: {
    title: 'Статистика',
    onCards: 'на картах',
    activeCards: (n: number) =>
      `${n} ${plural(n, 'активная карта', 'активные карты', 'активных карт')}`,
    thisMonth: 'в этом месяце',
    allTime: 'за всё время',
    sameAsLastMonth: 'как в прошлом месяце',
    vsLastMonth: (delta: string) => `${delta} к прошлому`,
    atRisk: 'Деньги под риском',
    expired: '⚠️ на истёкших картах',
    expiringIn: (days: number) => `⏳ истекает за ${days} дней`,
    inArchive: '📦 лежит в архиве',
    uncertain: '❔ остаток не подтверждён',
    whereItGoes: 'Куда уходит',
    whoSpends: 'Кто тратит',
    byMonth: 'По месяцам',
    left: (amount: string) => `осталось ${amount}`,
    purchases: (n: number) => `${n} ${plural(n, 'покупка', 'покупки', 'покупок')}`,
    nothingSpent: 'Пока ничего не потрачено.',
    tapColumn: 'Нажмите на столбец, чтобы увидеть сумму',
  },

  expiry: {
    expired: 'истёк',
    lastDay: 'сегодня последний день',
    days: (n: number) => `${n} ${plural(n, 'день', 'дня', 'дней')}`,
    until: (date: string) => `до ${date}`,
  },

  events: {
    created: 'создал купон',
    published: 'перевёл в активные',
    updated: 'изменил',
    balance_updated: 'обновил остаток',
    used: 'отметил использованным',
    unused: 'вернул в активные',
    archived: 'отправил в архив',
    restored: 'достал из архива',
    commented: 'оставил комментарий',
    image_replaced: 'заменил фото',
    spentLeft: (spent: string, left: string, note: string) =>
      `списал ${spent}, осталось ${left}${note}`,
    corrected: (left: string, note: string) => `поправил остаток: ${left}${note}`,
  },

  fields: {
    merchant: 'магазин',
    title: 'название',
    code: 'код',
    value_kind: 'тип скидки',
    value_amount: 'размер',
    currency: 'валюта',
    valid_from: 'начало',
    valid_until: 'срок',
    conditions: 'условия',
    notes: 'заметку',
    balance_uncertain: 'пометку «остаток не подтверждён»',
    balance_amount: 'остаток',
  },

  common: {
    back: 'Назад',
  },

  demo: {
    // A name, not "you": the history reads "<member> created the card", and a
    // pronoun there breaks verb agreement in both Russian and German.
    banner: 'Демо: карты ненастоящие, ничего не сохраняется',
    exit: 'Выйти',
    enter: 'Посмотреть демо',
    enterHint: 'Ненастоящие карты, но трогать можно всё',
    you: 'Макс',
    partner: 'Аня',
    errors: {
      spendTooMuch: (spent: string, current: string) =>
        `Нельзя списать ${spent} — на карте ${current}`,
      aboveFace: (face: string) => `Остаток больше номинала (${face}) — поправьте номинал`,
    },
    seed: {
      reweNote: 'подарили на день рождения',
      groceries: 'продукты',
      weeklyShop: 'закупка на неделю',
      shampoo: 'шампунь и зубная паста',
      candles: 'свечки и рамка',
      jetComment: 'кажется, уже потратили — надо проверить на кассе',
      totalComment: 'лежит в бардачке',
      kauflandComment: 'сгорает через неделю, давайте потратим',
      lidlComment: 'всё, пусто',
      douglasConditions: 'от 30 EUR',
    },
  },
}

/** Russian needs three forms; the helper stays here, next to the strings. */
function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few
  return many
}

export type Dictionary = typeof ru
