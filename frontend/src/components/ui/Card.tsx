import type { HTMLAttributes } from 'react'
import { CARD } from './cardClass'
import { cx } from './cx'

interface CardProps extends HTMLAttributes<HTMLElement> {
  as?: 'div' | 'section' | 'article' | 'li'
}

/** Flat panel: 1px hairline, no shadow, 24px padding. Do not nest cards. */
export function Card({ as: Tag = 'div', className, ...rest }: CardProps) {
  return <Tag className={cx(CARD, className)} {...rest} />
}
