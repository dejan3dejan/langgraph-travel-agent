// One hue per day, shared by the map markers/route lines and the day cards so they read as one plan.
// Wraps if a plan runs longer than the palette. These are a categorical data palette, theme-agnostic.
export const DAY_COLORS = ['#2563eb', '#db2777', '#16a34a', '#d97706', '#7c3aed', '#0891b2']

export const dayColor = (day) => DAY_COLORS[(day - 1) % DAY_COLORS.length]
