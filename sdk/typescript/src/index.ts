export class Foundry {
  constructor(private apiKey:string, private baseUrl="http://localhost:8000/api"){}
  private async request(path:string, init:RequestInit={}) { const r=await fetch(this.baseUrl+path,{...init,headers:{Authorization:`Bearer ${this.apiKey}`,"Content-Type":"application/json",...(init.headers||{})}}); if(!r.ok) throw new Error(`${r.status} ${await r.text()}`); return r.headers.get("content-type")?.includes("json")?r.json():r.arrayBuffer(); }
  createWorkspace(name:string){return this.request("/workspaces",{method:"POST",body:JSON.stringify({name})});}
  createComputer(workspace_id:string,name:string,spec={}){return this.request("/computers",{method:"POST",body:JSON.stringify({workspace_id,name,...spec})});}
  action(id:string,action:string,payload={}){return this.request(`/computers/${id}/${action}`,{method:"POST",body:JSON.stringify(payload)});}
}
