import { Button } from '@/components/ui/button'
import { openPlatformAdmin } from '@/platform/links'
import { useSession } from '@/session/session'
import { AuthLayout } from './AuthLayout'

export function BlockedScreen({ detail }: { detail: string }) {
  const { signOut } = useSession()
  return (
    <AuthLayout title="No access right now" subtitle={detail}>
      <p className="mb-5 text-sm text-muted-foreground">
        Your firm&rsquo;s owner or administrator can switch your access back on. If the whole firm is deactivated,
        contact AutoCA.
      </p>
      <Button className="w-full" onClick={() => void signOut()}>
        Sign out
      </Button>
    </AuthLayout>
  )
}

/** The platform owner belongs to no firm, so this application has nothing of theirs to show. */
export function PlatformOwnerScreen() {
  const { signOut, me } = useSession()
  return (
    <AuthLayout title="Platform administration" subtitle={`Signed in as ${me?.email ?? ''}.`}>
      <p className="mb-5 text-sm text-muted-foreground">
        This account is not part of any firm. Firms and their owners are managed in the platform admin.
      </p>
      <div className="grid gap-2">
        <Button className="w-full" onClick={openPlatformAdmin}>
          Open the platform admin
        </Button>
        <Button variant="ghost" className="w-full" onClick={() => void signOut()}>
          Sign out
        </Button>
      </div>
    </AuthLayout>
  )
}
