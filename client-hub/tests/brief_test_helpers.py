"""Exercise current brief/review routes from older checkout regression fixtures."""



def required_values(item):
    import wa_checkout
    return {key:(wa_checkout.FIELDS[key][1][0] if wa_checkout.FIELDS[key][1] else 'Test '+key)
            for key in wa_checkout.fields(item)[0]}


def complete_brief(client, url, reference=None):
    import catalog_service, projects_repo
    project_id=int(url.split('/')[2])
    project=projects_repo.get_project(project_id)
    item=catalog_service.get_catalog_item(project['catalog_key'])
    data={'action':'brief',**required_values(item)}
    if reference: data['reference_file']=reference
    response=client.post(url,data=data,content_type='multipart/form-data' if reference else None)
    assert response.status_code==302, response.status_code
    page=client.get(response.location)
    assert page.status_code==200 and 'Ringkasan brief' in page.get_data(as_text=True)
    project=projects_repo.get_project(project_id)
    response=client.post(url,data={'action':'confirm','review_version':project['requirements']['_review_version']})
    assert response.status_code==302, response.status_code
    return response
