// An amount written out in words the Indian way (lakh, crore), as a printed invoice shows it: "Rupees One Thousand Eighty and Fifty Paise Only".
// The amount is whole paise, like every amount in the app.

const ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
const TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

/** 0 to 99. */
function below100(n: number): string {
  if (n < 20) return ONES[n] ?? ''
  return [TENS[Math.floor(n / 10)], ONES[n % 10]].filter(Boolean).join(' ')
}

/** 0 to 999. */
function below1000(n: number): string {
  const hundreds = Math.floor(n / 100)
  return [hundreds ? `${ONES[hundreds]} Hundred` : '', below100(n % 100)].filter(Boolean).join(' ')
}

function wholeNumber(n: number): string {
  if (n === 0) return 'Zero'
  const parts: string[] = []
  const crore = Math.floor(n / 1_00_00_000)
  const lakh = Math.floor((n % 1_00_00_000) / 1_00_000)
  const thousand = Math.floor((n % 1_00_000) / 1_000)
  const rest = n % 1_000
  if (crore) parts.push(`${wholeNumber(crore)} Crore`)
  if (lakh) parts.push(`${below100(lakh)} Lakh`)
  if (thousand) parts.push(`${below100(thousand)} Thousand`)
  if (rest) parts.push(below1000(rest))
  return parts.join(' ')
}

export function amountInWords(paise: number): string {
  if (!Number.isInteger(paise)) throw new Error('An amount is whole paise.')
  const sign = paise < 0 ? 'Minus ' : ''
  const absolute = Math.abs(paise)
  const rupees = Math.floor(absolute / 100)
  const rest = absolute % 100
  const words = `Rupees ${wholeNumber(rupees)}${rest ? ` and ${below100(rest)} Paise` : ''} Only`
  return sign + words
}
