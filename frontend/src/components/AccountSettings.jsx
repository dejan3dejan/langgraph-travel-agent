import { useState } from 'react'

// Self-service account settings: edit profile basics, change password, and delete the account.
// Each section owns its own inputs and inline status so one failing action never blanks the others.
export default function AccountSettings({ auth, onClose }) {
  const user = auth.user
  const [username, setUsername] = useState(user?.username || '')
  const [email, setEmail] = useState(user?.email || '')
  const [profileMsg, setProfileMsg] = useState(null)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [pwMsg, setPwMsg] = useState(null)

  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deletePassword, setDeletePassword] = useState('')
  const [deleteMsg, setDeleteMsg] = useState(null)

  const [busy, setBusy] = useState(false)
  const [resendMsg, setResendMsg] = useState(null)

  const saveProfile = async (e) => {
    e.preventDefault()
    setBusy(true)
    setProfileMsg(null)
    const fields = {}
    if (username.trim() && username.trim() !== user.username) fields.username = username.trim()
    if (email.trim() && email.trim().toLowerCase() !== user.email) fields.email = email.trim()
    if (Object.keys(fields).length === 0) {
      setBusy(false)
      setProfileMsg({ ok: true, text: 'Nothing to update.' })
      return
    }
    const res = await auth.updateProfile(fields)
    setBusy(false)
    setProfileMsg(res.ok ? { ok: true, text: 'Profile updated.' } : { ok: false, text: res.error })
  }

  const savePassword = async (e) => {
    e.preventDefault()
    setBusy(true)
    setPwMsg(null)
    const res = await auth.changePassword(currentPassword, newPassword)
    setBusy(false)
    if (res.ok) {
      setCurrentPassword('')
      setNewPassword('')
      setPwMsg({ ok: true, text: 'Password changed.' })
    } else {
      setPwMsg({ ok: false, text: res.error })
    }
  }

  const removeAccount = async (e) => {
    e.preventDefault()
    setBusy(true)
    setDeleteMsg(null)
    const res = await auth.deleteAccount(deletePassword)
    setBusy(false)
    // On success the hook logs out, which unmounts this modal; only failures land here.
    if (!res.ok) setDeleteMsg(res.error)
  }

  const resend = async () => {
    setResendMsg(null)
    const res = await auth.resendVerification()
    setResendMsg(res.ok ? 'Verification email sent.' : res.error)
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="auth-card settings-card" onClick={(e) => e.stopPropagation()}>
        <h2 className="auth-card__title">Account settings</h2>

        {user && !user.email_verified && (
          <div className="settings-banner">
            <span>Your email is not verified.</span>
            <button type="button" className="auth-link-inline" onClick={resend}>Resend link</button>
            {resendMsg && <span className="settings-msg settings-msg--ok">{resendMsg}</span>}
          </div>
        )}

        <form className="auth-form settings-section" onSubmit={saveProfile}>
          <span className="settings-label">Profile</span>
          <input
            className="auth-input"
            type="text"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            minLength={2}
          />
          <input
            className="auth-input"
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          {profileMsg && (
            <p className={`settings-msg ${profileMsg.ok ? 'settings-msg--ok' : 'settings-msg--err'}`}>
              {profileMsg.text}
            </p>
          )}
          <button className="auth-submit" type="submit" disabled={busy}>Save profile</button>
        </form>

        <form className="auth-form settings-section" onSubmit={savePassword}>
          <span className="settings-label">Change password</span>
          <input
            className="auth-input"
            type="password"
            placeholder="Current password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            required
          />
          <input
            className="auth-input"
            type="password"
            placeholder="New password (6+ characters)"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            minLength={6}
          />
          {pwMsg && (
            <p className={`settings-msg ${pwMsg.ok ? 'settings-msg--ok' : 'settings-msg--err'}`}>{pwMsg.text}</p>
          )}
          <button className="auth-submit" type="submit" disabled={busy}>Change password</button>
        </form>

        <div className="auth-form settings-section">
          <span className="settings-label">Delete account</span>
          {!confirmDelete ? (
            <button type="button" className="settings-danger" onClick={() => setConfirmDelete(true)}>
              Delete my account
            </button>
          ) : (
            <form className="auth-form" onSubmit={removeAccount}>
              <p className="auth-note">This permanently removes your account, trips, and chats. Enter your password to confirm.</p>
              <input
                className="auth-input"
                type="password"
                placeholder="Password"
                value={deletePassword}
                onChange={(e) => setDeletePassword(e.target.value)}
                required
              />
              {deleteMsg && <p className="settings-msg settings-msg--err">{deleteMsg}</p>}
              <button className="settings-danger" type="submit" disabled={busy}>Permanently delete</button>
              <button type="button" className="auth-toggle" onClick={() => { setConfirmDelete(false); setDeleteMsg(null) }}>
                Cancel
              </button>
            </form>
          )}
        </div>

        <button className="auth-toggle" onClick={onClose}>Close</button>
      </div>
    </div>
  )
}
