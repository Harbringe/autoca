// A voucher's number as the Day Book shows it: ours, and under it Tally's own when the voucher was imported from there.

export function VoucherNo({ entryNo, tallyNumber }: { entryNo: number | string; tallyNumber?: string | null }) {
  return (
    <>
      <span>{entryNo}</span>
      {tallyNumber ? <span className="block text-xs font-normal text-muted-foreground">Tally {tallyNumber}</span> : null}
    </>
  )
}
