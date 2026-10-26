import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { API_BASE_URL } from '../api/client'
import { queryClient } from '../app/queryClient'

type AuthPayload = { access_token: string; user: { user_id: string; name: string; email: string } }

function GraphArtwork() {
  const nodes = [{x:82,y:112,r:10},{x:176,y:68,r:13},{x:266,y:125,r:9},{x:145,y:205,r:12},{x:260,y:238,r:10},{x:350,y:170,r:13},{x:380,y:78,r:7}]
  const edges = [[0,1],[1,2],[0,3],[3,4],[4,5],[2,5],[5,6],[1,3],[2,4]]
  return <svg viewBox="0 0 440 300" className="w-full max-w-lg" role="img" aria-label="Connected code graph nodes">
    <defs><linearGradient id="edge" x1="0" x2="1"><stop stopColor="#818cf8"/><stop offset="1" stopColor="#22d3ee"/></linearGradient><radialGradient id="node"><stop stopColor="#a5b4fc"/><stop offset="1" stopColor="#6366f1"/></radialGradient></defs>
    {edges.map(([a,b],i)=><line key={i} x1={nodes[a].x} y1={nodes[a].y} x2={nodes[b].x} y2={nodes[b].y} stroke="url(#edge)" strokeWidth="1.4" opacity=".6"/>)}
    {nodes.map((n,i)=><g key={i}><circle cx={n.x} cy={n.y} r={n.r+8} fill="#818cf8" opacity=".09"/><circle cx={n.x} cy={n.y} r={n.r} fill="url(#node)" stroke="#c7d2fe" strokeWidth="1"/><text x={n.x+14} y={n.y-13} fill="#cbd5e1" fontSize="10">{['main.py','parse()','GraphNode','embed()','retrieve()','answer()','API'][i]}</text></g>)}
    <rect x="32" y="252" width="150" height="29" rx="8" fill="#ffffff" fillOpacity=".06" stroke="#818cf8" strokeOpacity=".35"/><circle cx="47" cy="266" r="3" fill="#22d3ee"/><text x="57" y="270" fill="#cbd5e1" fontSize="10">CALLS · IMPORTS · DEFINES</text>
  </svg>
}

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const registering = mode === 'register'

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('')
    if (registering && password !== confirm) { setError('Your passwords do not match.'); return }
    if (registering && (!/[A-Za-z]/.test(password) || !/\d/.test(password))) { setError('Use at least one letter and one number in your password.'); return }
    setBusy(true)
    try {
      const response = await fetch(`${API_BASE_URL}/auth/${registering ? 'register' : 'login'}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(registering ? { name, email, password } : { email, password }) })
      const data = await response.json() as AuthPayload & { detail?: string; message?: string }
      if (!response.ok) throw new Error((typeof data.detail === 'string' ? data.detail : '') || data.message || 'Unable to sign in. Please check the details and try again.')
      queryClient.clear()
      sessionStorage.setItem('codegraph_access_token', data.access_token)
      sessionStorage.setItem('codegraph_user', JSON.stringify(data.user))
      const next = params.get('next')
      navigate(next?.startsWith('/') && !next.startsWith('//') ? next : '/', { replace: true })
    } catch (err) { setError(err instanceof Error ? err.message : 'A network error occurred. Please try again.') }
    finally { setBusy(false) }
  }

  return <main className="auth-page min-h-screen text-white">
    <section className="auth-brand-panel relative flex min-h-[280px] flex-col justify-between overflow-hidden px-7 py-8 md:min-h-screen md:w-1/2 md:px-12 md:py-12">
      <div className="auth-orb auth-orb-one"/><div className="auth-orb auth-orb-two"/>
      <Link to="/login" className="relative z-10 flex w-fit items-center gap-3 text-lg font-semibold tracking-tight"><span className="brand-mark">⌘</span> CodeGraph <span className="text-indigo-300">AI</span></Link>
      <div className="relative z-10 mx-auto w-full max-w-xl py-8">
        <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-indigo-300/20 bg-indigo-300/10 px-3 py-1.5 text-xs font-medium text-indigo-200"><span className="h-1.5 w-1.5 rounded-full bg-cyan-300"/> INTELLIGENT CODE UNDERSTANDING</div>
        <h1 className="max-w-xl text-4xl font-semibold leading-tight tracking-tight md:text-5xl">Understand Your Code.<br/><span className="auth-gradient-text">Discover Its Connections.</span></h1>
        <p className="mt-5 max-w-lg text-sm leading-7 text-slate-300 md:text-base">Explore your codebase with AI-powered Retrieval-Augmented Generation and knowledge graphs. Trace relationships, find relevant code, and understand how the pieces fit together.</p>
        <div className="mt-8 flex justify-center"><GraphArtwork/></div>
        <div className="mt-4 grid max-w-lg grid-cols-3 gap-3">{[['01','Static analysis'],['02','Knowledge graph'],['03','Grounded answers']].map(([n,t])=><div key={n} className="rounded-xl border border-white/10 bg-white/[0.04] p-3"><div className="text-xs font-semibold text-indigo-300">{n}</div><div className="mt-1 text-xs text-slate-300">{t}</div></div>)}</div>
      </div>
      <p className="relative z-10 text-xs text-slate-500">Built for developers who want to see beyond the code.</p>
    </section>
    <section className="flex min-h-[560px] flex-1 items-center justify-center px-6 py-12 md:min-h-screen md:w-1/2 md:px-10">
      <div className="w-full max-w-md">
        <div className="mb-8 md:hidden"><span className="brand-mark mr-3">⌘</span><span className="font-semibold">CodeGraph AI</span></div>
        <p className="text-sm font-medium text-indigo-300">YOUR CODEBASE, CONNECTED</p>
        <h2 className="mt-3 text-3xl font-semibold tracking-tight">{registering ? 'Create your account' : 'Welcome Back'}</h2>
        <p className="mt-2 text-sm text-slate-400">{registering ? 'Start exploring your code with clarity.' : 'Sign in to continue to your workspace.'}</p>
        <form onSubmit={submit} className="mt-8 space-y-5">
          {registering && <div><label htmlFor="name" className="mb-2 block text-sm font-medium text-slate-300">Full name</label><input id="name" autoComplete="name" required minLength={2} maxLength={120} value={name} onChange={e=>setName(e.target.value)} placeholder="Your name" className="auth-input"/></div>}
          <div><label htmlFor="email" className="mb-2 block text-sm font-medium text-slate-300">Email address</label><input id="email" type="email" autoComplete="email" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@example.com" className="auth-input"/></div>
          <div><label htmlFor="password" className="mb-2 block text-sm font-medium text-slate-300">Password</label><div className="relative"><input id="password" type={showPassword ? 'text' : 'password'} autoComplete={registering ? 'new-password' : 'current-password'} required minLength={registering ? 10 : 1} value={password} onChange={e=>setPassword(e.target.value)} placeholder={registering ? 'At least 10 characters' : 'Enter your password'} className="auth-input pr-20"/><button type="button" onClick={()=>setShowPassword(v=>!v)} className="absolute inset-y-0 right-3 text-xs font-medium text-indigo-300 hover:text-white">{showPassword ? 'Hide' : 'Show'}</button></div>{registering && <p className="mt-2 text-xs text-slate-500">Use 10+ characters with at least one letter and one number.</p>}</div>
          {registering && <div><label htmlFor="confirm" className="mb-2 block text-sm font-medium text-slate-300">Confirm password</label><input id="confirm" type={showPassword ? 'text' : 'password'} autoComplete="new-password" required value={confirm} onChange={e=>setConfirm(e.target.value)} placeholder="Re-enter your password" className="auth-input"/></div>}
          {error && <div role="alert" className="rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>}
          <button type="submit" disabled={busy} className="auth-submit">{busy ? <><span className="auth-spinner"/> {registering ? 'Creating account…' : 'Signing in…'}</> : registering ? 'Create account' : 'Sign in'}<span aria-hidden="true">→</span></button>
        </form>
        <p className="mt-7 text-center text-sm text-slate-400">{registering ? 'Already have an account?' : "Don't have an account?"} <Link className="font-semibold text-indigo-300 hover:text-indigo-200" to={registering ? '/login' : '/register'}>{registering ? 'Sign in' : 'Create account'}</Link></p>
        <p className="mt-10 text-center text-xs leading-5 text-slate-600">Your repositories are private to your account.<br/>CodeGraph AI · Source code stays yours.</p>
      </div>
    </section>
  </main>
}
