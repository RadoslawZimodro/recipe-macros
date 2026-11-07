import { MatchesSection } from './MatchesSection'
import { PantrySection, StaplesSection } from './PantryLists'

export function PantryPage() {
  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">Lodówka</h1>
      <div className="grid gap-8 md:grid-cols-2">
        <PantrySection />
        <StaplesSection />
      </div>
      <MatchesSection />
    </div>
  )
}
