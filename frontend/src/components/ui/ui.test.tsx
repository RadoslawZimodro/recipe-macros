import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Button } from './Button'
import { ErrorMessage } from './ErrorMessage'
import { Modal } from './Modal'
import { SegmentedControl } from './SegmentedControl'

describe('Button', () => {
  it('defaults to type=button and fires onClick', async () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Zapisz</Button>)
    const button = screen.getByRole('button', { name: 'Zapisz' })
    expect(button).toHaveAttribute('type', 'button')
    await userEvent.click(button)
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('is disabled and busy while loading, and does not fire onClick', async () => {
    const onClick = vi.fn()
    render(<Button loading onClick={onClick}>Zapisz</Button>)
    const button = screen.getByRole('button', { name: 'Zapisz' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')
    await userEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })
})

describe('ErrorMessage', () => {
  it('renders nothing without a message', () => {
    const { container } = render(<ErrorMessage message={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the message as an alert and offers a retry only when asked', async () => {
    const onRetry = vi.fn()
    const { rerender } = render(<ErrorMessage message="Błąd" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Błąd')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    rerender(<ErrorMessage message="Błąd" onRetry={onRetry} />)
    await userEvent.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})

describe('SegmentedControl', () => {
  const options = [
    { value: 'a', label: 'Jeden' },
    { value: 'b', label: 'Dwa' },
  ]

  function Harness({ mode }: { mode: 'tabs' | 'toggle' }) {
    const [value, setValue] = useState('a')
    return <SegmentedControl label="Wybór" options={options} value={value} onChange={setValue} mode={mode} />
  }

  it('toggle mode uses aria-pressed', async () => {
    render(<Harness mode="toggle" />)
    expect(screen.getByRole('button', { name: 'Jeden' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Dwa' }))
    expect(screen.getByRole('button', { name: 'Dwa' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Jeden' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('tabs mode uses role=tab, roving tabindex and arrow keys', async () => {
    render(<Harness mode="tabs" />)
    expect(screen.getByRole('tablist', { name: 'Wybór' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Dwa' })).toHaveAttribute('tabindex', '-1')
    screen.getByRole('tab', { name: 'Jeden' }).focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Dwa' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Dwa' })).toHaveFocus()
    await userEvent.keyboard('{ArrowRight}') // wraps around
    expect(screen.getByRole('tab', { name: 'Jeden' })).toHaveAttribute('aria-selected', 'true')
  })
})

describe('Modal', () => {
  function Harness({ onClose = () => {} }: { onClose?: () => void }) {
    const [open, setOpen] = useState(false)
    return (
      <>
        <button onClick={() => setOpen(true)}>Otwórz</button>
        <Modal
          open={open}
          onClose={() => {
            setOpen(false)
            onClose()
          }}
          title="Potwierdź"
        >
          <button onClick={() => setOpen(false)}>Anuluj</button>
        </Modal>
      </>
    )
  }

  it('is hidden until opened, then labelled by its title', async () => {
    render(<Harness />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Otwórz' }))
    expect(screen.getByRole('dialog', { name: 'Potwierdź' })).toBeInTheDocument()
  })

  it('closes from its own button and calls onClose', async () => {
    const onClose = vi.fn()
    render(<Harness onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: 'Otwórz' }))
    await userEvent.click(screen.getByRole('button', { name: 'Anuluj' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(onClose).toHaveBeenCalled()
  })
})
