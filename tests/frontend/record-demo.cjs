// A silent, labelled local recording; this is not a rehearsal of the team's speech.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
(async()=>{
  const base=process.argv[2]||'http://127.0.0.1:15186', output=path.resolve(process.argv[3]||'artifacts/submission-final/demo');
  if(new URL(base).hostname!=='127.0.0.1')throw Error('Local demo only');
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch();
  try{
    const context=await browser.newContext({viewport:{width:1440,height:900},recordVideo:{dir:output,size:{width:1440,height:900}},acceptDownloads:true});
    let blocked=0;
    await context.route('**/*',route=>{if(new URL(route.request().url()).origin===base)return route.continue();blocked++;return route.abort();});
    const page=await context.newPage();await page.goto(base);await page.getByTestId('total').waitFor();
    const caps=await (await page.request.get(base+'/api/v2/handoff/capabilities')).json();
    await page.evaluate(run=>{const d=document.createElement('div');d.id='recording-caption';d.style.cssText='position:fixed;bottom:0;left:0;right:0;background:#091722;color:white;padding:18px 28px;z-index:9999;font:18px sans-serif;border-top:3px solid #f01835';d.textContent='';document.body.append(d);document.body.style.paddingBottom='85px';d.dataset.run=run;},caps.forecast_run_id);
    const start=Date.now();
    async function caption(text,until){await page.locator('#recording-caption').evaluate((el,t)=>el.textContent='РЕЗЕРВНАЯ ЗАПИСЬ · '+t,text);const wait=start+until*1000-Date.now();if(wait>0)await page.waitForTimeout(wait);}
    await caption('TramFlow · исторический прогноз 2025 · успешные посадки, не заполненность',10);
    await page.getByLabel('Маршрут',{exact:true}).selectOption('__overview__');await page.locator('[data-overview-route="17"]').waitFor();
    await caption('Обзор: сравниваем одинаковые интервалы. № 5 — отдельный baseline.',20);
    await page.getByRole('button',{name:'№ 17',exact:true}).click();await page.getByTestId('total').waitFor();
    const data=await (await page.request.post(base+'/api/v2/handoff/query',{data:{route_ids:['17'],start:caps.start,end:'2025-11-02T00:00:00+03:00',resolution:'hour',forecast_run_id:caps.forecast_run_id}})).json();
    const peak=data.rows.reduce((p,r,i)=>r.value>data.rows[p].value?i:p,0);
    await page.getByLabel('Точка временного ряда').focus();await page.keyboard.press('Home');for(let i=0;i<peak;i++)await page.keyboard.press('ArrowRight');
    await page.getByTestId('map-demand').scrollIntoViewIfNeeded();
    await caption('Маршрут 17: пик и соседние часы. Следующее действие — проверить выпуск и интервалы.',30);
    await page.locator('.scenario-panel summary').click();
    await page.getByLabel('Коэффициент погоды').focus();for(let i=0;i<2;i++)await page.keyboard.press('ArrowRight');
    await page.getByLabel('Коэффициент события').focus();for(let i=0;i<4;i++)await page.keyboard.press('ArrowRight');
    await page.locator('[data-scenario-total]').waitFor();await page.locator('.scenario-panel').scrollIntoViewIfNeeded();
    await caption('Ручные допущения: 1,10 × 1,20 = 1,32. База, сценарий и разница; это не ML-эффект.',42);
    const download=page.waitForEvent('download');await page.getByRole('button',{name:'Скачать CSV',exact:true}).click();await (await download).saveAs(path.join(output,'demo-scenario-route17.csv'));
    await page.getByRole('button',{name:'Таблица',exact:true}).click();await page.locator('.forecast-card__visual').scrollIntoViewIfNeeded();
    await caption('CSV закреплён за показанным сценарием: база, значение, разница и коэффициенты.',52);
    await page.getByRole('button',{name:'Сбросить сценарий',exact:true}).click();await page.getByRole('button',{name:'1 мес',exact:true}).click();await page.getByTestId('total').waitFor();await page.evaluate(()=>scrollTo(0,0));
    await caption('Сброс возвращает базу. Месяц показывает суммы по дням.',62);
    await page.getByRole('button',{name:'Год',exact:true}).click();await page.getByRole('region',{name:'Качественный год'}).waitFor();
    await caption('Год — три качественных сценария. Численная сумма и интервал не оценены.',75);
    const video=page.video();await context.close();await video.saveAs(path.join(output,'demo.webm'));
    fs.writeFileSync(path.join(output,'recording.json'),JSON.stringify({run:caps.forecast_run_id,duration_seconds:(Date.now()-start)/1000,blocked_external_requests:blocked,external_requests_allowed:false,type:'silent_labelled_technical_demo',human_rehearsal:false},null,2));
    console.log('Recorded local 75-second demo with external requests blocked.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
