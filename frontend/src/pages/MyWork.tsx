import { useState } from 'react'
import { useSession } from '../auth/session'
import { Spinner } from '../components/ui'
import WorkPanel, { RangePicker } from './team/WorkPanel'

export default function MyWork() {
  const { me } = useSession()
  const [rangeKey, setRangeKey] = useState('month')
  if (!me?.membership_id) return <Spinner />
  return (
    <>
      <div className="page-head">
        <div>
          <h1>My work</h1>
          <p className="sub">What you've done, and what is still open on the clients you work on.</p>
        </div>
        <div className="actions">
          <RangePicker value={rangeKey} onChange={setRangeKey} />
        </div>
      </div>
      <WorkPanel memberId={me.membership_id} rangeKey={rangeKey} />
    </>
  )
}
