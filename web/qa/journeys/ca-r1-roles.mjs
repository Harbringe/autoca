import { signedIn, shot } from '../lib/session.mjs'
const CID='73d99780-eca9-48e7-8ab2-a8e1cee1271f'
for (const role of ['senior','staff','reader']) {
  const { page, problems, close } = await signedIn(role)
  for (const p of ['','/statements','/review','/daybook','/reports','/books','/masters']) {
    await page.goto(`http://127.0.0.1:5173/clients/${CID}${p}`); await page.waitForTimeout(1300)
    const btns=(await page.getByRole('button').allInnerTexts()).map(s=>s.replace(/\n/g,' ').trim()).filter(s=>s&&!/^(AA|SS|SU|RR|Any|High|Check|Decide)$/.test(s))
    const links=(await page.getByRole('link').allInnerTexts()).filter(s=>/Confirm|Send|Upload|Tally/.test(s))
    console.log(role,p||'/','BUTTONS:',JSON.stringify(btns),'LINKS:',JSON.stringify(links))
  }
  await shot(page,'r1-ca-role-'+role+'-books'); console.log(role,'problems',problems); await close()
}
