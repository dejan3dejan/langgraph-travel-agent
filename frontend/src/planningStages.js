// Maps each pipeline node to an instrument and a pool of cartographer-voice lines. The pool is what
// lets the caption feel alive: the SSE handler picks one at random each time a stage goes active.
// Pure and I/O-free on purpose, so the random pick lives at the boundary (useChat), not here.

export const PLANNING_STAGES = {
  interviewer: {
    variant: 'compass',
    lines: [
      'Getting our bearings',
      'Finding true north',
      'Unfolding the map',
      'Sharpening the pencils',
    ],
  },
  research_food: {
    variant: 'globe',
    lines: [
      'Sniffing out the local tables',
      'Following our nose to lunch',
      'Asking the locals where they eat',
      'Hunting down a proper meal',
    ],
  },
  research_activity: {
    variant: 'globe',
    lines: [
      'Charting sights worth your time',
      'Circling the must-sees',
      'Marking an X on the good spots',
      'Scouting the interesting corners',
    ],
  },
  research_hotel: {
    variant: 'globe',
    lines: [
      'Scouting a comfy basecamp',
      'Finding somewhere to rest',
      'Testing the pillows (virtually)',
      'Pinning down a good bed',
    ],
  },
  logistics: {
    variant: 'radar',
    lines: [
      'Plotting the smartest route',
      'Connecting the dots',
      'Saving you the backtracking',
      'Lining up your days',
    ],
  },
  compiler: {
    variant: 'globe',
    lines: [
      'Inking your itinerary',
      'Putting pen to paper',
      'Writing it all up',
      'Drawing the final map',
    ],
  },
  critic: {
    variant: 'compass',
    lines: [
      'Double-checking the map',
      'Squinting at the details',
      'Making sure it all flows',
    ],
  },
}

const FALLBACK = { variant: 'compass', lines: ['Charting your trip', 'Plotting your adventure'] }

export function stageFor(node) {
  return PLANNING_STAGES[node] || FALLBACK
}
