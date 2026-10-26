import type { StylesheetJson } from 'cytoscape'
import type { NodeLabel, RelationshipType } from '../../types/api'

// See Prompt 11 "Graph Node Types": distinguish node types by shape, not
// color alone. Also used for the legend and the node-type filter list.
export const NODE_SHAPE_BY_LABEL: Record<NodeLabel, string> = {
  File: 'round-rectangle',
  Module: 'round-rectangle',
  Class: 'rectangle',
  Function: 'ellipse',
  Method: 'ellipse',
  APIEndpoint: 'hexagon',
  ExternalDependency: 'diamond',
  Parameter: 'ellipse',
  Directory: 'round-rectangle',
  Repository: 'round-rectangle',
}

export const NODE_COLOR_BY_LABEL: Record<NodeLabel, string> = {
  File: '#64748b',
  Module: '#64748b',
  Class: '#a855f7',
  Function: '#38bdf8',
  Method: '#38bdf8',
  APIEndpoint: '#f59e0b',
  ExternalDependency: '#f43f5e',
  Parameter: '#94a3b8',
  Directory: '#475569',
  Repository: '#334155',
}

export const NODE_BADGE_BY_LABEL: Record<NodeLabel, string> = {
  File: 'F',
  Module: 'M',
  Class: 'C',
  Function: 'ƒ',
  Method: 'ƒ',
  APIEndpoint: 'API',
  ExternalDependency: 'ext',
  Parameter: 'p',
  Directory: 'dir',
  Repository: 'repo',
}

export const EDGE_COLOR_BY_TYPE: Record<RelationshipType, string> = {
  CALLS: '#38bdf8',
  IMPORTS: '#94a3b8',
  EXTENDS: '#a855f7',
  DEFINES: '#475569',
  HANDLED_BY: '#f59e0b',
  DEPENDS_ON: '#f43f5e',
  CONTAINS: '#334155',
  HAS_PARAMETER: '#334155',
  REFERENCES: '#94a3b8',
}

export const GRAPH_LEGEND: { label: NodeLabel; description: string }[] = [
  { label: 'Class', description: 'rectangle' },
  { label: 'Function', description: 'ellipse (ƒ)' },
  { label: 'Method', description: 'ellipse (ƒ)' },
  { label: 'APIEndpoint', description: 'hexagon' },
  { label: 'File', description: 'rounded rectangle' },
  { label: 'ExternalDependency', description: 'diamond' },
]

export function cytoscapeStylesheet(): StylesheetJson {
  return [
    {
      selector: 'node',
      style: {
        label: 'data(label)',
        'font-size': 9,
        color: '#e2e8f0',
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'background-color': 'data(color)',
        shape: 'data(shape)' as never,
        width: 26,
        height: 26,
        'border-width': 2,
        'border-color': '#0f172a',
      },
    },
    {
      selector: 'node:selected',
      style: {
        'border-color': '#facc15',
        'border-width': 3,
      },
    },
    {
      selector: 'node[?isTarget]',
      style: {
        'border-color': '#facc15',
        'border-width': 4,
        width: 34,
        height: 34,
      },
    },
    {
      selector: 'edge',
      style: {
        width: 1.5,
        'line-color': 'data(color)',
        'target-arrow-color': 'data(color)',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'font-size': 7,
        color: '#94a3b8',
      },
    },
  ]
}
