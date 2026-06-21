import { useState } from 'react'

// First-run intake: a short, skippable set of preferences so the first itinerary lands well and
// Atlas stops re-asking the same opening questions. Single-select for vibe/budget/pace, multi for
// interests and dietary needs. Each option's value is the lowercase token the planner reads.
const SINGLE = {
  vibe: ['Relaxing', 'Romantic', 'Adventure', 'Cultural', 'Family', 'Foodie'],
  budget: ['Low', 'Medium', 'High'],
  pace: ['Relaxed', 'Balanced', 'Packed'],
}
const MULTI = {
  interests: ['Food', 'Museums', 'Nightlife', 'Outdoors', 'Shopping', 'History', 'Art', 'Beaches'],
  dietary: ['Vegetarian', 'Vegan', 'Halal', 'Kosher', 'Gluten-free'],
}

// Budget is a fixed enum the planner reads verbatim (Low/Medium/High); everything else is free text,
// so it goes through lowercased.
const valueFor = (group, label) => (group === 'budget' ? label : label.toLowerCase())

function ChipGroup({ group, label, options, selected, onToggle }) {
  return (
    <div className="intake-group">
      <span className="intake-group__label">{label}</span>
      <div className="intake-chips">
        {options.map((opt) => {
          const v = valueFor(group, opt)
          const active = Array.isArray(selected) ? selected.includes(v) : selected === v
          return (
            <button
              key={opt}
              type="button"
              className={`intake-chip ${active ? 'is-active' : ''}`}
              aria-pressed={active}
              onClick={() => onToggle(v)}
            >
              {opt}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default function Intake({ onComplete, onSkip }) {
  const [single, setSingle] = useState({ vibe: '', budget: '', pace: '' })
  const [multi, setMulti] = useState({ interests: [], dietary: [] })

  // Clicking the active single-select option again clears it, so a tap is always reversible.
  const toggleSingle = (key) => (v) => setSingle((s) => ({ ...s, [key]: s[key] === v ? '' : v }))
  const toggleMulti = (key) => (v) =>
    setMulti((m) => ({ ...m, [key]: m[key].includes(v) ? m[key].filter((x) => x !== v) : [...m[key], v] }))

  const submit = () => {
    const prefs = {}
    for (const key of Object.keys(single)) if (single[key]) prefs[key] = single[key]
    for (const key of Object.keys(multi)) if (multi[key].length) prefs[key] = multi[key]
    onComplete(prefs)
  }

  return (
    <div className="intake">
      <h2 className="intake__heading">
        First, a few <em>preferences</em>
      </h2>
      <p className="intake__sub">
        Tell me your travel style and I'll tailor the first plan to it. Skip any of it, you can
        change your mind in the chat anytime.
      </p>

      <ChipGroup group="vibe" label="Vibe" options={SINGLE.vibe} selected={single.vibe} onToggle={toggleSingle('vibe')} />
      <ChipGroup group="budget" label="Budget" options={SINGLE.budget} selected={single.budget} onToggle={toggleSingle('budget')} />
      <ChipGroup group="pace" label="Pace" options={SINGLE.pace} selected={single.pace} onToggle={toggleSingle('pace')} />
      <ChipGroup group="interests" label="Interests" options={MULTI.interests} selected={multi.interests} onToggle={toggleMulti('interests')} />
      <ChipGroup group="dietary" label="Dietary needs" options={MULTI.dietary} selected={multi.dietary} onToggle={toggleMulti('dietary')} />

      <div className="intake__actions">
        <button className="intake__start" type="button" onClick={submit}>
          Start planning
        </button>
        <button className="intake__skip" type="button" onClick={onSkip}>
          Skip for now
        </button>
      </div>
    </div>
  )
}
