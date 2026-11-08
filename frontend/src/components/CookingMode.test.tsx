import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef, useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { IngredientLine, RecipeStep } from '../api/recipes'
import { CookingMode } from './CookingMode'

const STEPS: RecipeStep[] = [
  { position: 1, instruction: 'Pokrój cebulę.', image_url: null },
  { position: 2, instruction: 'Podsmaż cebulę.', image_url: '/recipes/7/steps/2/image' },
  { position: 3, instruction: 'Dodaj jajka.', image_url: null },
]
const INGREDIENTS = [{ id: 1, raw_text: '2 jajka' }] as IngredientLine[]

function Harness({ steps = STEPS, onClose }: { steps?: RecipeStep[]; onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  const button = useRef<HTMLButtonElement>(null)
  return (
    <>
      <button ref={button} onClick={() => setOpen(true)} disabled={steps.length === 0}>
        Tryb gotowania
      </button>
      <CookingMode
        open={open}
        onClose={() => {
          setOpen(false)
          onClose?.()
        }}
        title="Szakszuka"
        steps={steps}
        ingredients={INGREDIENTS}
        opener={button}
      />
    </>
  )
}

async function openDialog() {
  const user = userEvent.setup()
  render(<Harness />)
  await user.click(screen.getByRole('button', { name: 'Tryb gotowania' }))
  return user
}

describe('CookingMode', () => {
  it('is disabled for a recipe without steps', () => {
    render(<Harness steps={[]} />)
    expect(screen.getByRole('button', { name: 'Tryb gotowania' })).toBeDisabled()
  })

  it('shows the first step with counter and no Back', async () => {
    await openDialog()
    expect(screen.getByRole('dialog', { name: 'Szakszuka' })).toBeInTheDocument()
    expect(screen.getByText('Krok 1 z 3')).toBeInTheDocument()
    expect(screen.getByText('Pokrój cebulę.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Wstecz' })).toBeDisabled()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('moves with buttons, arrows and the step buttons; the last step offers Zakończ', async () => {
    const user = await openDialog()
    await user.click(screen.getByRole('button', { name: 'Dalej' }))
    expect(screen.getByText('Krok 2 z 3')).toBeInTheDocument()
    expect(screen.getByRole('img')).toHaveAttribute('src', expect.stringMatching(/\/recipes\/7\/steps\/2\/image$/))
    await user.keyboard('{ArrowRight}')
    expect(screen.getByText('Krok 3 z 3')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Dalej' })).not.toBeInTheDocument()
    await user.keyboard('{ArrowLeft}')
    expect(screen.getByText('Krok 2 z 3')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Krok 3' }))
    expect(screen.getByText('Dodaj jajka.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Wstecz' }))
    expect(screen.getByText('Krok 2 z 3')).toBeInTheDocument()
  })

  it('hides a photo that fails to load and keeps the step text', async () => {
    const user = await openDialog()
    await user.click(screen.getByRole('button', { name: 'Dalej' }))
    fireEvent.error(screen.getByRole('img'))
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByText('Podsmaż cebulę.')).toBeInTheDocument()
  })

  it.each([undefined, '@evil.example/x', '//evil', 'http://evil.example/recipes/1/steps/1/image', 'javascript:alert(1)'])(
    'renders no photo for image_url %s',
    async (bad) => {
      const user = userEvent.setup()
      const steps = [
        { position: 1, instruction: 'Pierwszy.', image_url: bad as unknown as string },
        { position: 2, instruction: 'Drugi.', image_url: bad as unknown as string },
      ]
      render(<Harness steps={steps} />)
      await user.click(screen.getByRole('button', { name: 'Tryb gotowania' }))
      expect(screen.queryByRole('img')).not.toBeInTheDocument()
      expect(screen.getByText('Pierwszy.')).toBeInTheDocument()
    },
  )

  it('has a collapsed ingredients panel that can be opened', async () => {
    const user = await openDialog()
    const summary = screen.getByText('Składniki')
    const details = summary.closest('details')!
    expect(details).not.toHaveAttribute('open')
    await user.click(summary)
    expect(details).toHaveAttribute('open')
    expect(screen.getByText('2 jajka')).toBeInTheDocument()
  })

  it('closes once on Escape (cancel event), then on Zakończ and a backdrop click; focus returns to the opener', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(<Harness onClose={onClose} />)
    const opener = screen.getByRole('button', { name: 'Tryb gotowania' })
    await user.click(opener)
    // jsdom has no Escape handling for <dialog>; the browser fires "cancel", so do the same.
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('Krok 1 z 3')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()

    await user.click(opener)
    await user.click(screen.getByRole('button', { name: 'Krok 3' }))
    await user.click(screen.getByRole('button', { name: 'Zakończ' }))
    expect(screen.queryByText('Krok 3 z 3')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()

    await user.click(opener)
    expect(screen.getByText('Krok 1 z 3')).toBeInTheDocument() // reopens at the first step
    await user.click(screen.getByRole('dialog')) // the dialog element itself is the backdrop
    expect(screen.queryByText('Krok 1 z 3')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('restores the previous body overflow after closing and after unmounting', async () => {
    document.body.style.overflow = 'scroll'
    const user = userEvent.setup()
    const { unmount } = render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Tryb gotowania' }))
    expect(document.body.style.overflow).toBe('hidden')
    await user.click(screen.getByRole('button', { name: 'Zamknij tryb gotowania' }))
    expect(document.body.style.overflow).toBe('scroll')
    await user.click(screen.getByRole('button', { name: 'Tryb gotowania' }))
    unmount()
    expect(document.body.style.overflow).toBe('scroll')
    document.body.style.overflow = ''
  })

  it('changes step on arrows even when the key lands on the step text or the dialog', async () => {
    await openDialog()
    fireEvent.keyDown(screen.getByText('Pokrój cebulę.'), { key: 'ArrowRight' })
    expect(screen.getByText('Krok 2 z 3')).toBeInTheDocument()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'ArrowLeft' })
    expect(screen.getByText('Krok 1 z 3')).toBeInTheDocument()
  })

  it('renders nothing and does not throw without steps', () => {
    const { container } = render(
      <CookingMode open onClose={() => {}} title="X" steps={[]} ingredients={[]} opener={{ current: null }} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('clamps to the last step when the steps shrink while open', async () => {
    const user = userEvent.setup()
    const props = { open: true, onClose: () => {}, title: 'X', ingredients: INGREDIENTS, opener: { current: null } }
    const { rerender } = render(<CookingMode {...props} steps={STEPS} />)
    await user.click(screen.getByRole('button', { name: 'Krok 3' }))
    rerender(<CookingMode {...props} steps={STEPS.slice(0, 2)} />)
    expect(screen.getByText('Krok 2 z 2')).toBeInTheDocument()
    expect(screen.getByText('Podsmaż cebulę.')).toBeInTheDocument()
  })

  it('remembers a failed photo per URL', async () => {
    const steps: RecipeStep[] = [
      { position: 1, instruction: 'Jeden.', image_url: null },
      { position: 2, instruction: 'Dwa.', image_url: '/recipes/7/steps/2/image' },
      { position: 3, instruction: 'Trzy.', image_url: '/recipes/7/steps/3/image' },
    ]
    const user = userEvent.setup()
    render(<Harness steps={steps} />)
    await user.click(screen.getByRole('button', { name: 'Tryb gotowania' }))
    await user.click(screen.getByRole('button', { name: 'Krok 2' }))
    fireEvent.error(screen.getByRole('img'))
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Krok 3' }))
    expect(screen.getByRole('img')).toHaveAttribute('src', expect.stringMatching(/steps\/3\/image$/))
    await user.click(screen.getByRole('button', { name: 'Krok 2' }))
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('keeps a fixed-height dialog and a photo slot on every step, with or without a photo', async () => {
    const user = await openDialog()
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveClass('h-dvh', 'sm:h-[min(90dvh,44rem)]')
    const slot = screen.getByTestId('step-photo-slot')
    expect(slot).toBeInTheDocument() // step 1 has no photo
    await user.click(screen.getByRole('button', { name: 'Dalej' }))
    expect(screen.getByTestId('step-photo-slot')).toContainElement(screen.getByRole('img'))
    fireEvent.error(screen.getByRole('img'))
    expect(screen.getByTestId('step-photo-slot')).toBeInTheDocument()
    expect(dialog).toHaveClass('h-dvh', 'sm:h-[min(90dvh,44rem)]')
  })

  it('scrolls the step text back to the top when the step changes', async () => {
    const user = await openDialog()
    const text = screen.getByText('Pokrój cebulę.').parentElement!
    expect(text).toHaveClass('overflow-y-auto')
    text.scrollTop = 80
    await user.click(screen.getByRole('button', { name: 'Dalej' }))
    expect(text.scrollTop).toBe(0)
  })
})
