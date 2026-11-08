/** Flat panel: 1px hairline, no shadow, 24px padding. */
export const CARD = 'rounded-md border border-line bg-surface p-6'

/** A whole card that is a link: hairline firms up and the surface lifts on hover. */
export const CARD_LINK = `${CARD} transition-[background-color,border-color] duration-150 ease-soft hover:border-line-strong hover:bg-raised`
