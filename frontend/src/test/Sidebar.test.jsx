import { render, screen, fireEvent } from '@testing-library/react'
import Sidebar from '../components/Sidebar'

const owned = [{ id: 't1', destination: 'Rome', duration: '3 days', budget: 'Medium', created_at: '2026-06-01' }]
const shared = [
  { id: 't2', destination: 'Lisbon', duration: '2 days', budget: 'Low', created_at: '2026-06-02', role: 'editor', owner: 'mia' },
]

function setup(props = {}) {
  return render(
    <Sidebar
      trips={owned}
      sharedTrips={shared}
      loading={false}
      error={null}
      onSelect={() => {}}
      onDelete={() => {}}
      onInvite={() => {}}
      onClose={() => {}}
      {...props}
    />,
  )
}

test('lists owned trips under saved trips', () => {
  setup()
  expect(screen.getByText('Rome')).toBeInTheDocument()
})

test('shows shared trips in a distinct section with owner and role', () => {
  setup()
  expect(screen.getByText(/shared with you/i)).toBeInTheDocument()
  expect(screen.getByText('Lisbon')).toBeInTheDocument()
  expect(screen.getByText(/mia/)).toBeInTheDocument()
  expect(screen.getByText(/editor/i)).toBeInTheDocument()
})

test('does not render the shared section when nothing is shared', () => {
  setup({ sharedTrips: [] })
  expect(screen.queryByText(/shared with you/i)).not.toBeInTheDocument()
})

test('invites a collaborator by email and role from an owned trip', () => {
  const onInvite = vi.fn()
  setup({ onInvite })
  fireEvent.click(screen.getByRole('button', { name: /share trip/i }))
  fireEvent.change(screen.getByPlaceholderText(/email/i), { target: { value: 'pat@x.com' } })
  fireEvent.change(screen.getByLabelText(/role/i), { target: { value: 'editor' } })
  fireEvent.click(screen.getByRole('button', { name: /^invite$/i }))
  expect(onInvite).toHaveBeenCalledWith('t1', 'pat@x.com', 'editor')
})
