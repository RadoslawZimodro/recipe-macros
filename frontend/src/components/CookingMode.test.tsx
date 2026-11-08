import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef, useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { IngredientLine, RecipeStep } from '../api/recipes'
import { CookingMode } from './CookingMode'

const STEPS: RecipeStep[] = [
  { position: 1, instruction: 'Pokrój cebulę.', image_url: null },
  { position: 2, instruction: 'Podsmaż cebulę.', image_url: '/recipes/7/steps/2/image' },
  { position: 3, instruction: 'Dodaj jajka.', image_url: null },
]
const INGREDIENTS = [{ id: 1, raw_text: '2 jajka' }] as IngredientLine[]

function Harness({ steps = STEPS }: { steps?: RecipeStep[] }) {
  const [open, setOpen] = useState(false)
  const button = useRef<HTMLButtonElement>(null)
  return (
    <>
      <button ref={button} onClick={() => setOpen(true)} disabled={steps.length === 0}>
        Tryb gotowania
      </button>
      <CookingMode
        open={open}
        onClose={() => setOpen(false)}
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

  it('closes with Escape, Zakończ and a backdrop click, returning focus to the opener', async () => {
    const user = await openDialog()
    const opener = screen.getByRole('button', { name: 'Tryb gotowania', hidden: true })
    await user.click(screen.getByRole('button', { name: 'Krok 1' })) // jsdom does not move focus into the dialog
    await user.keyboard('{Escape}')
    expect(screen.queryByText('Krok 1 z 3')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()

    await user.click(opener)
    await user.click(screen.getByRole('button', { name: 'Krok 3' }))
    await user.click(screen.getByRole('button', { name: 'Zakończ' }))
    expect(screen.queryByText('Krok 3 z 3')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()

    await user.click(opener)
    await user.click(screen.getByRole('dialog')) // the dialog element itself is the backdrop
    expect(screen.queryByText('Krok 1 z 3')).not.toBeInTheDocument()
  })

  it('locks page scrolling while open', async () => {
    const user = await openDialog()
    expect(document.body.style.overflow).toBe('hidden')
    await user.click(screen.getByRole('button', { name: 'Krok 1' })) // jsdom does not move focus into the dialog
    await user.keyboard('{Escape}')
    expect(document.body.style.overflow).toBe('')
  })
})
