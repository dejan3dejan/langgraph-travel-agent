import { PLANNING_STAGES, stageFor } from '../planningStages'

test('maps each pipeline node to the right instrument', () => {
  expect(stageFor('interviewer').variant).toBe('compass')
  expect(stageFor('research_food').variant).toBe('globe')
  expect(stageFor('research_activity').variant).toBe('globe')
  expect(stageFor('research_hotel').variant).toBe('globe')
  expect(stageFor('logistics').variant).toBe('radar')
  expect(stageFor('compiler').variant).toBe('globe')
})

test('falls back to a sensible stage for an unknown node instead of throwing', () => {
  const s = stageFor('some_future_node')
  expect(s.variant).toBeTruthy()
  expect(s.lines.length).toBeGreaterThan(0)
})

test('every stage has a non-empty pool of lines so the random pick always has something', () => {
  for (const stage of Object.values(PLANNING_STAGES)) {
    expect(stage.lines.length).toBeGreaterThan(0)
  }
})

test('no planning line uses an em dash (house rule)', () => {
  const lines = Object.values(PLANNING_STAGES).flatMap((s) => s.lines)
  expect(lines.every((l) => !l.includes('—'))).toBe(true)
})
