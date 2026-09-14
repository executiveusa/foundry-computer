import httpx
class Foundry:
    def __init__(self,api_key:str,base_url:str="http://localhost:8000/api"):
        self.http=httpx.Client(base_url=base_url,headers={"Authorization":f"Bearer {api_key}"})
    def create_workspace(self,name): return self._post("/workspaces",{"name":name})
    def create_computer(self,workspace_id,name,**spec): return self._post("/computers",{"workspace_id":workspace_id,"name":name,**spec})
    def action(self,computer_id,action,**payload): return self._post(f"/computers/{computer_id}/{action}",payload)
    def screenshot(self,computer_id): r=self.http.get(f"/computers/{computer_id}/screenshot"); r.raise_for_status(); return r.content
    def _post(self,path,data): r=self.http.post(path,json=data); r.raise_for_status(); return r.json()
