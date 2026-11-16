const state={busy:false};
document.querySelectorAll("[data-endpoint]").forEach(btn=>{
  if(btn.tagName==="FORM")return;
  btn.addEventListener("click",async()=>{
    if(state.busy)return; state.busy=true; const out=btn.parentElement.querySelector(".result"); out.textContent="运行中";
    try{const res=await fetch(btn.dataset.endpoint,{method:btn.dataset.endpoint.includes("export")?"GET":"POST",headers:{"content-type":"application/json"},body:btn.dataset.endpoint.includes("export")?null:"{}"});out.textContent=await res.text()}catch(e){out.textContent="请求失败，请重试"}finally{state.busy=false}
  })});
// 撤回/续办表单：明文标识只在本次请求传输，响应只回不可逆凭据。
document.querySelectorAll("form.withdraw-form").forEach(form=>{
  const out=form.parentElement.querySelector(".result");
  const send=async endpoint=>{
    if(state.busy)return; state.busy=true; out.textContent="办理中";
    const payload={service:form.service.value,request_id:form.request_id.value};
    try{
      const res=await fetch(endpoint,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});
      out.textContent=JSON.stringify(await res.json(),null,2);
      if(res.ok)setTimeout(()=>location.reload(),600);
    }catch(e){out.textContent="请求失败，可使用中断续办按已扣贡献重试"}finally{state.busy=false}
  };
  form.addEventListener("submit",e=>{
    e.preventDefault();
    const resume=e.submitter&&e.submitter.dataset&&e.submitter.dataset.resume==="1";
    send(resume?"/api/runs/withdraw/resume":form.dataset.endpoint);
  });
});
document.querySelector("#refresh")?.addEventListener("click",()=>location.reload());
