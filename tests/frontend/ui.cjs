// Shared navigation for the compact workspace; no application state is bypassed.
const visible = locator => locator.filter({visible:true});
async function setTheme(page, theme) {
  if (await page.locator('html').getAttribute('data-theme') === theme) return;
  const mobile = page.viewportSize().width < 700;
  if (mobile) await page.getByRole('button',{name:'Открыть меню',exact:true}).click();
  await visible(page.getByRole('button',{name:theme === 'dark' ? 'Включить тёмную тему' : 'Включить светлую тему',exact:true})).click();
  if (mobile) await page.getByRole('button',{name:'Закрыть меню',exact:true}).press('Escape');
}
async function openData(page, tab = 'Источники') {
  await page.getByRole('button',{name:page.viewportSize().width < 700 ? 'Данные' : 'О данных',exact:true}).click();
  await page.getByRole('dialog',{name:'О данных',exact:true}).getByRole('button',{name:tab,exact:true}).click();
}
async function closeDialog(page) { await page.getByRole('button',{name:'Закрыть окно',exact:true}).click(); }
async function refreshForecast(page) {
  await openData(page, 'Прогноз');
  await page.getByRole('button',{name:'Обновить прогноз',exact:true}).click();
  await closeDialog(page);
}
async function readRun(page) {
  await openData(page, 'Паспорт');
  const run = await page.getByTestId('run').textContent();
  await closeDialog(page);
  return run;
}
async function mobilePane(page, name) {
  if (page.viewportSize().width < 700) await page.getByRole('navigation',{name:'Основные экраны'}).getByRole('button',{name,exact:true}).click();
}
async function openScenario(page) {
  await visible(page.getByRole('button',{name:/^Поправки/})).first().click();
}
async function applyScenario(page, changes) {
  await openScenario(page);
  for (const [label, percent] of Object.entries(changes)) await page.getByLabel(`Поправка: ${label}`,{exact:true}).fill(String(percent));
  const response = page.waitForResponse(r => /\/(?:scenarios|handoff)\/query$/.test(r.url()) && r.ok());
  await page.getByRole('button',{name:'Применить',exact:true}).click();
  return (await response).json();
}
module.exports = {visible, setTheme, openData, closeDialog, refreshForecast, readRun, mobilePane, openScenario, applyScenario};
