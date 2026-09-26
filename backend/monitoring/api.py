from fastapi import APIRouter, HTTPException, Query, Request, Response

router=APIRouter(prefix='/api/v2/monitoring',tags=['Operational monitoring'])


def service(request):
    monitor=getattr(request.app.state,'monitor',None)
    if monitor is None: raise HTTPException(503,'Мониторинг запускается')
    return monitor


@router.get('/status')
def status(request: Request, response: Response):
    response.headers['Cache-Control']='no-store'
    return service(request).view()


@router.get('/records')
def records(request: Request, response: Response, source_id: str, offset: int=Query(0,ge=0), limit: int=Query(50,ge=1,le=100)):
    response.headers['Cache-Control']='no-store'
    monitor=service(request)
    if source_id not in monitor.rows: raise HTTPException(404,'Неизвестный источник')
    return monitor.records(source_id,offset,limit)
