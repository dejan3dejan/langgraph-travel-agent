const PROMPTS = [
  'Plan a 3-day trip to Rome on a medium budget',
  'Romantic weekend in Paris for two',
  'Family adventure in Tokyo, 5 days with kids',
  'Backpacking through Barcelona and Lisbon',
]

export default function Welcome({ onPrompt }) {
  return (
    <div className="welcome">
      <span className="welcome__globe">🌍</span>
      <h2 className="welcome__heading">
        Where shall we <em>explore</em>?
      </h2>
      <p className="welcome__sub">
        Tell me your destination, duration, and budget — I'll chart a
        day-by-day itinerary with real restaurants, activities, and hotels.
      </p>
      <p className="welcome__scope">Travel planning only: destinations, food, activities, and stays.</p>
      <div className="prompt-chips">
        {PROMPTS.map((p) => (
          <button key={p} className="prompt-chip" onClick={() => onPrompt(p)}>
            {p}
          </button>
        ))}
      </div>
    </div>
  )
}
