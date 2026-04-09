# API Integration Examples

## Complete Workflow Examples

### Example 1: Job Processing Pipeline

Complete workflow from job creation to annotation with sync.

```typescript
// workflow.ts
import { JBIApiClient } from './api-client';

const api = new JBIApiClient('http://localhost:8000/api/v1', token);

async function processVideoWorkflow(videoFile: File) {
  // 1. Upload video
  console.log('Step 1: Uploading video...');
  const upload = await api.uploads.create(videoFile);
  const jobId = upload.job_id;
  
  // 2. Poll for Stage 1 completion
  console.log('Step 2: Waiting for detection...');
  await api.jobs.waitForStatus(jobId, 'ASR_COMPLETED', {
    onProgress: (status) => console.log(`Progress: ${status.progress}%`)
  });
  
  // 3. Get Stage 1 results (detection)
  const stage1 = await api.stageResults.getStage1(jobId);
  console.log(`Detected ${stage1.total_segments} segments`);
  
  // 4. Poll for Stage 2 completion
  console.log('Step 4: Waiting for ASR...');
  await api.jobs.waitForStatus(jobId, 'CROPPING');
  
  // 5. Get Stage 2 results (ASR)
  const stage2 = await api.stageResults.getStage2(jobId);
  console.log(`ASR found ${stage2.total_utterances} utterances`);
  
  // Show low confidence warnings
  const lowConfidence = stage2.results.flatMap(r => 
    r.utterances.filter(u => u.confidence < 0.7)
  );
  if (lowConfidence.length > 0) {
    console.warn(`${lowConfidence.length} utterances need ASR review`);
  }
  
  // 6. Poll for Stage 3 completion
  console.log('Step 6: Waiting for cropping...');
  await api.jobs.waitForStatus(jobId, 'READY_FOR_ANNOTATION');
  
  // 7. Get Stage 3 results (cropped videos)
  const stage3 = await api.stageResults.getStage3(jobId);
  console.log(`Cropping complete: ${stage3.summary.cropped}/${stage3.summary.total_utterances}`);
  
  return {
    jobId,
    stage1,
    stage2,
    stage3
  };
}
```

### Example 2: Admin Audit Dashboard

```typescript
// admin-dashboard.tsx
import React, { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, PieChart, Pie, Cell } from 'recharts';

export function AdminAuditDashboard() {
  const [stats, setStats] = useState(null);
  const [logs, setLogs] = useState([]);
  const [filters, setFilters] = useState({
    days: 7,
    action: '',
    actor_id: ''
  });

  // Load stats on mount
  useEffect(() => {
    loadStats();
    loadLogs();
  }, [filters]);

  const loadStats = async () => {
    const response = await fetch(
      `/api/v1/admin/audit/stats?days=${filters.days}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    const data = await response.json();
    setStats(data);
  };

  const loadLogs = async () => {
    const params = new URLSearchParams();
    params.append('page', '1');
    params.append('page_size', '50');
    if (filters.action) params.append('action', filters.action);
    if (filters.actor_id) params.append('actor_id', filters.actor_id);
    
    const response = await fetch(
      `/api/v1/admin/audit/logs?${params}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    const data = await response.json();
    setLogs(data.items);
  };

  const exportLogs = async (format: 'json' | 'csv') => {
    const params = new URLSearchParams();
    params.append('format', format);
    params.append('days', String(filters.days));
    
    const response = await fetch(
      `/api/v1/admin/audit/export?${params}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `audit_export_${new Date().toISOString().split('T')[0]}.${format}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  if (!stats) return <div>Loading...</div>;

  return (
    <div className="admin-dashboard">
      <header>
        <h1>Audit Dashboard</h1>
        <div className="export-buttons">
          <button onClick={() => exportLogs('csv')}>Export CSV</button>
          <button onClick={() => exportLogs('json')}>Export JSON</button>
        </div>
      </header>

      {/* Stats Cards */}
      <div className="stats-grid">
        <StatCard
          title="Total Actions"
          value={stats.total_logs}
          icon="activity"
        />
        <StatCard
          title="Active Users"
          value={stats.unique_users}
          icon="users"
        />
        <StatCard
          title="Period"
          value={`${new Date(stats.period_start).toLocaleDateString()} - ${new Date(stats.period_end).toLocaleDateString()}`}
          icon="calendar"
        />
      </div>

      {/* Charts */}
      <div className="charts-grid">
        <div className="chart-card">
          <h3>Daily Activity</h3>
          <LineChart width={600} height={300} data={stats.daily_activity}>
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="count" stroke="#3b82f6" />
          </LineChart>
        </div>

        <div className="chart-card">
          <h3>Top Actions</h3>
          <PieChart width={400} height={300}>
            <Pie
              data={stats.top_actions}
              dataKey="count"
              nameKey="label"
              cx={200}
              cy={150}
              outerRadius={100}
            >
              {stats.top_actions.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </div>
      </div>

      {/* Activity Log Table */}
      <div className="log-table">
        <h3>Recent Activity</h3>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>User</th>
              <th>Action</th>
              <th>Resource</th>
              <th>IP Address</th>
            </tr>
          </thead>
          <tbody>
            {logs.map(log => (
              <tr key={log.id}>
                <td>{new Date(log.timestamp).toLocaleString()}</td>
                <td>{log.actor?.email || 'System'}</td>
                <td>
                  <span className={`action-badge ${log.action.split('.')[0]}`}>
                    {log.action_label}
                  </span>
                </td>
                <td>{log.resource.type}:{log.resource.id.slice(0, 8)}...</td>
                <td>{log.ip_address}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6'];
```

### Example 3: Sync Workbench with Keyboard Shortcuts

```typescript
// sync-workbench-advanced.tsx
import React, { useEffect, useCallback } from 'react';

export function AdvancedSyncWorkbench({ editId, token }) {
  const [sync, setSync] = useState(null);
  const [videoRef, setVideoRef] = useState<HTMLVideoElement>(null);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!videoRef) return;

      switch (e.key) {
        case ' ':
          e.preventDefault();
          videoRef.paused ? videoRef.play() : videoRef.pause();
          break;
        case 'ArrowLeft':
          e.preventDefault();
          videoRef.currentTime -= 0.1; // -100ms
          break;
        case 'ArrowRight':
          e.preventDefault();
          videoRef.currentTime += 0.1; // +100ms
          break;
        case '[':
          adjustBoundary('start', -0.1);
          break;
        case ']':
          adjustBoundary('start', 0.1);
          break;
        case '{':
          adjustBoundary('end', -0.1);
          break;
        case '}':
          adjustBoundary('end', 0.1);
          break;
        case 'l':
          if (e.ctrlKey) {
            e.preventDefault();
            lockSync();
          }
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [videoRef, sync]);

  const adjustBoundary = async (target: 'start' | 'end', delta: number) => {
    await fetch(`/api/v1/annotations/sync/${editId}/fine-tune`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        adjustment_ms: delta * 1000,
        target
      })
    });
    refreshSync();
  };

  const lockSync = async () => {
    await fetch(`/api/v1/annotations/sync/${editId}/validate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        text_match: true,
        video_complete: true,
        sync_locked: true
      })
    });
    refreshSync();
  };

  return (
    <div className="sync-workbench-advanced">
      {/* Video Player */}
      <div className="video-section">
        <video
          ref={setVideoRef}
          src={previewUrl}
          controls
        />
        
        {/* Timecode overlay */}
        <div className="timecode-overlay">
          {videoRef && (
            <>
              <span className="current">{formatTime(videoRef.currentTime)}</span>
              <span className="separator"> / </span>
              <span className="duration">{formatTime(videoRef.duration)}</span>
            </>
          )}
        </div>
      </div>

      {/* Keyboard shortcut help */}
      <div className="shortcuts-help">
        <h4>Keyboard Shortcuts</h4>
        <dl>
          <dt>Space</dt><dd>Play/Pause</dd>
          <dt>← / →</dt><dd>Seek -100ms / +100ms</dd>
          <dt>[ / ]</dt><dd>Adjust start -100ms / +100ms</dd>
          <dt>{'{'} / {'}'}</dt><dd>Adjust end -100ms / +100ms</dd>
          <dt>Ctrl+L</dt><dd>Lock sync</dd>
        </dl>
      </div>

      {/* Rest of the UI... */}
    </div>
  );
}
```

---

## API Client Library

### TypeScript Client

```typescript
// api-client.ts
export class JBIApiClient {
  private baseUrl: string;
  private token: string;

  constructor(baseUrl: string, token: string) {
    this.baseUrl = baseUrl;
    this.token = token;
  }

  private async request<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers: {
        'Authorization': `Bearer ${this.token}`,
        'Content-Type': 'application/json',
        ...options.headers
      }
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'API request failed');
    }

    return response.json();
  }

  // Stage Results API
  stageResults = {
    getStage1: (jobId: string) => 
      this.request(`/pipeline/jobs/${jobId}/stage1/results`),
    
    getStage2: (jobId: string) => 
      this.request(`/pipeline/jobs/${jobId}/stage2/results`),
    
    getStage3: (jobId: string) => 
      this.request(`/pipeline/jobs/${jobId}/stage3/results`)
  };

  // Audit Log API
  audit = {
    getLogs: (params?: { page?: number; page_size?: number; action?: string }) => {
      const query = new URLSearchParams();
      if (params?.page) query.append('page', String(params.page));
      if (params?.page_size) query.append('page_size', String(params.page_size));
      if (params?.action) query.append('action', params.action);
      return this.request(`/admin/audit/logs?${query}`);
    },
    
    getStats: (days?: number) => 
      this.request(`/admin/audit/stats?days=${days || 30}`),
    
    export: (format: 'json' | 'csv', filters?: any) => {
      const query = new URLSearchParams();
      query.append('format', format);
      if (filters?.days) query.append('days', String(filters.days));
      return fetch(`${this.baseUrl}/admin/audit/export?${query}`, {
        headers: { 'Authorization': `Bearer ${this.token}` }
      });
    }
  };

  // Sync API
  sync = {
    get: (editId: string) => 
      this.request(`/annotations/sync/${editId}`),
    
    update: (editId: string, data: {
      video_start_offset?: number;
      video_end_offset?: number;
      glosa?: string;
    }) => this.request(`/annotations/sync/${editId}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),
    
    fineTune: (editId: string, adjustment_ms: number, target: 'start' | 'end' | 'both') =>
      this.request(`/annotations/sync/${editId}/fine-tune`, {
        method: 'POST',
        body: JSON.stringify({ adjustment_ms, target })
      }),
    
    validate: (editId: string, indicators: {
      text_match: boolean;
      video_complete: boolean;
      sync_locked: boolean;
    }) => this.request(`/annotations/sync/${editId}/validate`, {
      method: 'POST',
      body: JSON.stringify(indicators)
    }),
    
    getPreview: (editId: string) => 
      this.request(`/annotations/sync/${editId}/preview`)
  };

  // Jobs API
  jobs = {
    get: (jobId: string) => 
      this.request(`/pipeline/jobs/${jobId}`),
    
    waitForStatus: async (
      jobId: string,
      targetStatus: string,
      options?: { onProgress?: (status: any) => void; timeout?: number }
    ) => {
      const startTime = Date.now();
      const timeout = options?.timeout || 300000; // 5 minutes
      
      while (Date.now() - startTime < timeout) {
        const job = await this.jobs.get(jobId);
        
        if (job.status === targetStatus || job.status === 'FAILED') {
          return job;
        }
        
        options?.onProgress?.(job);
        await new Promise(r => setTimeout(r, 5000)); // Poll every 5s
      }
      
      throw new Error('Timeout waiting for job status');
    }
  };
}
```

---

## Testing

### Unit Tests with Jest

```typescript
// api-client.test.ts
import { JBIApiClient } from './api-client';

const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('JBIApiClient', () => {
  const client = new JBIApiClient('http://api.test', 'test-token');

  beforeEach(() => {
    mockFetch.mockClear();
  });

  test('stageResults.getStage1', async () => {
    const mockResponse = {
      id: 'job-1',
      total_segments: 5,
      results: []
    };

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(mockResponse)
    });

    const result = await client.stageResults.getStage1('job-1');
    
    expect(mockFetch).toHaveBeenCalledWith(
      'http://api.test/pipeline/jobs/job-1/stage1/results',
      expect.objectContaining({
        headers: expect.objectContaining({
          'Authorization': 'Bearer test-token'
        })
      })
    );
    expect(result.total_segments).toBe(5);
  });

  test('audit.getLogs with filters', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ items: [], total: 0 })
    });

    await client.audit.getLogs({ page: 2, page_size: 20, action: 'user.login' });
    
    expect(mockFetch).toHaveBeenCalledWith(
      'http://api.test/admin/audit/logs?page=2&page_size=20&action=user.login',
      expect.any(Object)
    );
  });

  test('sync.fineTune', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ adjustment_ms: 100 })
    });

    await client.sync.fineTune('edit-1', 100, 'end');
    
    expect(mockFetch).toHaveBeenCalledWith(
      'http://api.test/annotations/sync/edit-1/fine-tune',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ adjustment_ms: 100, target: 'end' })
      })
    );
  });
});
```

---

## Error Handling Patterns

```typescript
// error-handler.ts
export class APIError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string
  ) {
    super(message);
  }
}

export async function handleAPIRequest<T>(
  request: Promise<T>,
  options?: {
    onError?: (error: APIError) => void;
    retry?: number;
  }
): Promise<T> {
  let retries = options?.retry || 0;
  
  while (true) {
    try {
      return await request;
    } catch (error: any) {
      // Network error
      if (!error.status) {
        if (retries > 0) {
          retries--;
          await new Promise(r => setTimeout(r, 1000));
          continue;
        }
        throw new APIError('Network error', 0, 'NETWORK_ERROR');
      }
      
      // Auth error - redirect to login
      if (error.status === 401) {
        window.location.href = '/login';
        throw new APIError('Session expired', 401, 'UNAUTHORIZED');
      }
      
      // Permission error
      if (error.status === 403) {
        const apiError = new APIError(
          'Insufficient permissions',
          403,
          'FORBIDDEN'
        );
        options?.onError?.(apiError);
        throw apiError;
      }
      
      // Other errors
      const apiError = new APIError(
        error.message || 'API error',
        error.status,
        error.code || 'UNKNOWN'
      );
      options?.onError?.(apiError);
      throw apiError;
    }
  }
}

// Usage
const data = await handleAPIRequest(
  api.stageResults.getStage1(jobId),
  {
    onError: (error) => {
      toast.error(error.message);
    },
    retry: 3
  }
);
```

---

## Performance Optimization

```typescript
// cache.ts
export class APICache {
  private cache = new Map<string, { data: any; expiry: number }>();
  
  get<T>(key: string): T | null {
    const entry = this.cache.get(key);
    if (!entry) return null;
    if (Date.now() > entry.expiry) {
      this.cache.delete(key);
      return null;
    }
    return entry.data;
  }
  
  set(key: string, data: any, ttlMs: number) {
    this.cache.set(key, { data, expiry: Date.now() + ttlMs });
  }
  
  invalidate(pattern: RegExp) {
    for (const key of this.cache.keys()) {
      if (pattern.test(key)) {
        this.cache.delete(key);
      }
    }
  }
}

// Usage with React Query
import { useQuery, useQueryClient } from '@tanstack/react-query';

function useStage2Results(jobId: string) {
  return useQuery({
    queryKey: ['stage2', jobId],
    queryFn: () => api.stageResults.getStage2(jobId),
    staleTime: 5 * 60 * 1000, // 5 minutes - stage results don't change
    cacheTime: 30 * 60 * 1000 // 30 minutes
  });
}
```
