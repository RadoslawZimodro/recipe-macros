import { NavLink } from 'react-router-dom'
import { cx } from './cx'

export interface NavItem {
  to: string
  label: string
}

/** Main navigation; the current route gets aria-current="page" from NavLink. */
export function Nav({ items }: { items: NavItem[] }) {
  return (
    <nav aria-label="Główna" className="flex flex-1 gap-1">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            cx(
              'inline-flex h-10 items-center rounded-sm px-3 text-body font-medium transition-[color,background-color] duration-150 ease-soft hover:bg-raised',
              isActive ? 'text-ink' : 'text-ink-3 hover:text-ink',
            )
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}
