import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as repositoriesApi from '../../api/repositories'
import { renderWithProviders } from '../../tests/testUtils'
import type { Repository } from '../../types/api'
import { ImportRepositoryDialog } from './ImportRepositoryDialog'

vi.mock('../../api/repositories')
const mockedRepositories = vi.mocked(repositoriesApi)

function repository(overrides: Partial<Repository> = {}): Repository {
  return {
    repository_id: 'repo-9',
    name: 'imported',
    source_type: 'zip_upload',
    source_location: 'imported.zip',
    status: 'ready',
    default_branch: null,
    commit_sha: null,
    file_count: 3,
    error_message: null,
    file_stats: null,
    created_at: null,
    last_indexed_at: null,
    ...overrides,
  }
}

describe('ImportRepositoryDialog', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders nothing when closed', () => {
    renderWithProviders(<ImportRepositoryDialog open={false} onClose={vi.fn()} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('defaults to the Upload ZIP tab and disables Import until a name and file are set', async () => {
    renderWithProviders(<ImportRepositoryDialog open onClose={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Upload ZIP' })).toHaveClass('bg-slate-700')
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled()
  })

  it('switches to the Clone Git tab and requires a URL before enabling Import', async () => {
    renderWithProviders(<ImportRepositoryDialog open onClose={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Clone Git Repository' }))
    expect(screen.getByPlaceholderText('https://github.com/example/project.git')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Repository name'), { target: { value: 'demo' } })
    fireEvent.change(screen.getByPlaceholderText('https://github.com/example/project.git'), {
      target: { value: 'https://github.com/example/demo.git' },
    })
    expect(screen.getByRole('button', { name: 'Import' })).toBeEnabled()
  })

  it('clones and navigates to the new repository on success', async () => {
    mockedRepositories.cloneRepository.mockResolvedValue(repository({ repository_id: 'repo-42' }))
    renderWithProviders(<ImportRepositoryDialog open onClose={vi.fn()} />, {
      route: '/',
      path: '/',
    })

    fireEvent.click(screen.getByRole('button', { name: 'Clone Git Repository' }))
    fireEvent.change(screen.getByLabelText('Repository name'), { target: { value: 'demo' } })
    fireEvent.change(screen.getByPlaceholderText('https://github.com/example/project.git'), {
      target: { value: 'https://github.com/example/demo.git' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Import' }))

    await waitFor(() =>
      expect(mockedRepositories.cloneRepository).toHaveBeenCalledWith(
        'demo',
        'https://github.com/example/demo.git',
      ),
    )
  })

  it('shows a friendly error state if import fails', async () => {
    mockedRepositories.cloneRepository.mockRejectedValue(new Error('clone failed'))
    renderWithProviders(<ImportRepositoryDialog open onClose={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Clone Git Repository' }))
    fireEvent.change(screen.getByLabelText('Repository name'), { target: { value: 'demo' } })
    fireEvent.change(screen.getByPlaceholderText('https://github.com/example/project.git'), {
      target: { value: 'https://github.com/example/demo.git' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Import' }))

    expect(
      await screen.findByText(
        (_content, element) =>
          element?.tagName === 'P' &&
          Boolean(element.textContent?.includes('Something unexpected went wrong.')),
      ),
    ).toBeInTheDocument()
  })
})
