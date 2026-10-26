import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { cloneRepository, uploadRepository } from '../../api/repositories'
import { Dialog } from '../../components/common/Dialog'
import { ErrorState } from '../../components/common/ErrorState'

type Tab = 'zip' | 'git'

/** See Prompt 11 "Repository Import": Upload ZIP / Clone Git tabs, drag
 * and drop, filename/size preview, Git URL form, navigate to the
 * repository's analysis page on success. */
export function ImportRepositoryDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>('zip')
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [gitUrl, setGitUrl] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const uploadMutation = useMutation({
    mutationFn: () => uploadRepository(name.trim(), file as File),
    onSuccess: (repository) => {
      void queryClient.invalidateQueries({ queryKey: ['repositories'] })
      handleClose()
      navigate(`/repositories/${repository.repository_id}`)
    },
  })

  const cloneMutation = useMutation({
    mutationFn: () => cloneRepository(name.trim(), gitUrl.trim()),
    onSuccess: (repository) => {
      void queryClient.invalidateQueries({ queryKey: ['repositories'] })
      handleClose()
      navigate(`/repositories/${repository.repository_id}`)
    },
  })

  const handleClose = useCallback(() => {
    setName('')
    setFile(null)
    setGitUrl('')
    uploadMutation.reset()
    cloneMutation.reset()
    onClose()
  }, [onClose, uploadMutation, cloneMutation])

  function onDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragOver(false)
    const dropped = event.dataTransfer.files[0]
    if (dropped && dropped.name.toLowerCase().endsWith('.zip')) {
      setFile(dropped)
    }
  }

  const pending = uploadMutation.isPending || cloneMutation.isPending

  return (
    <Dialog open={open} onClose={handleClose} title="Import Repository">
      <div className="mb-4 flex gap-1 rounded bg-slate-800 p-1 text-sm">
        <button
          type="button"
          className={`flex-1 rounded px-2 py-1 ${tab === 'zip' ? 'bg-slate-700 text-white' : 'text-slate-400'}`}
          onClick={() => setTab('zip')}
        >
          Upload ZIP
        </button>
        <button
          type="button"
          className={`flex-1 rounded px-2 py-1 ${tab === 'git' ? 'bg-slate-700 text-white' : 'text-slate-400'}`}
          onClick={() => setTab('git')}
        >
          Clone Git Repository
        </button>
      </div>

      <label className="mb-3 block text-sm">
        <span className="mb-1 block text-slate-300">Repository name</span>
        <input
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
          placeholder="my-project"
        />
      </label>

      {tab === 'zip' ? (
        <div
          onDragOver={(event) => {
            event.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className={`rounded border-2 border-dashed p-6 text-center text-sm ${
            dragOver ? 'border-sky-500 bg-sky-500/5' : 'border-slate-700'
          }`}
        >
          {file ? (
            <p className="text-slate-200">
              {file.name} <span className="text-slate-500">({Math.round(file.size / 1024)} KB)</span>
            </p>
          ) : (
            <p className="text-slate-400">Drag and drop a .zip file here, or</p>
          )}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="mt-2 rounded border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:bg-slate-800"
          >
            Choose file
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </div>
      ) : (
        <label className="block text-sm">
          <span className="mb-1 block text-slate-300">Public HTTPS Git URL</span>
          <input
            type="text"
            value={gitUrl}
            onChange={(event) => setGitUrl(event.target.value)}
            className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
            placeholder="https://github.com/example/project.git"
          />
          <p className="mt-1 text-xs text-slate-500">
            Only public github.com and gitlab.com HTTPS URLs are supported — no
            private repositories, SSH URLs, or credentials in the URL.
          </p>
        </label>
      )}

      {(uploadMutation.isError || cloneMutation.isError) && (
        <div className="mt-3">
          <ErrorState error={uploadMutation.error ?? cloneMutation.error} />
        </div>
      )}

      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={handleClose}
          className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
        >
          Cancel
        </button>
        <button
          type="button"
          disabled={pending || !name.trim() || (tab === 'zip' ? !file : !gitUrl.trim())}
          onClick={() => (tab === 'zip' ? uploadMutation.mutate() : cloneMutation.mutate())}
          className="rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {pending ? 'Importing…' : 'Import'}
        </button>
      </div>
    </Dialog>
  )
}