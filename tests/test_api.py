import json

def test_health(client): assert client.get('/health/ready').status_code==200
def test_product_ai_publication_flow(client):
    r=client.post('/products',data={'name':'Туман'},follow_redirects=False);assert r.status_code==303;product_id=r.headers['location'].split('/')[-1]
    page=client.get(f'/products/{product_id}/ai');assert page.status_code==200
    import re
    request_id=re.search(r'BCP-[0-9]{8}-[A-F0-9]+',page.text).group(0)
    payload={"schema_version":"bamboo-content-pack/1.0","request_id":request_id,"product":{"price":{"amount":3900,"currency":"RUB"}},"channels":{"telegram":{"text":"Новая чашка","button_text":"","button_url":""}}}
    r=client.post(f'/api/products/{product_id}/ai/import',json={'text':json.dumps(payload,ensure_ascii=False)});assert r.status_code==200
    r=client.post(f'/products/{product_id}/publications',data={'channels':'demo','action':'publish'},follow_redirects=False);assert r.status_code==303
    assert client.get('/publications').status_code==200
