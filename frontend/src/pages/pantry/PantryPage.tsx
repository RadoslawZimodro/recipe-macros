import { MatchesSection } from './MatchesSection'
import { PantrySection, StaplesSection } from './PantryLists'

export function PantryPage() {
  return (
    <div className="space-y-12">
      <h1 className="text-h1">Lodówka</h1>
      <div className="grid gap-8 md:grid-cols-2">
        <PantrySection />
        <StaplesSection />
      </div>
      <MatchesSection />
    </div>
  )
}
