interface ProgressData {
    loaded: number;
    total: number;
    progress: number;
}

export type { ProgressData };
  
/**
 * Fetch with progress tracking
 * @param url - The URL to fetch from
 * @param options - Fetch options
 * @param onProgress - Progress callback function that receives:
 *   - loaded: number of bytes loaded
 *   - total: total bytes (if known) or 0 if unknown
 *   - progress: percentage complete (0-100) or -1 if total size unknown
 * @returns Promise<Response> - The fetch response
 */
export async function fetchProgress(
    url: string,
    options: RequestInit = {},
    onProgress: (progress: ProgressData) => void
): Promise<Response> {
    // Start the fetch
    const response = await fetch(url, options);

    // Get the total size if available
    const total = parseInt(response.headers.get('content-length') || '1');

    // Create a ReadableStream to track the download
    const reader = response.body!.getReader();
    let loaded = 0;

    // Read the data stream
    const stream = new ReadableStream({
        async start(controller) {
        while (true) {
            const {done, value} = await reader.read();
            
            if (done) {
            controller.close();
            break;
            }
            
            // Update progress
            loaded += value.length;
            const progress = total ? Math.round((loaded / total) * 100) : -1;
            
            onProgress({
            loaded,
            total,
            progress
            });
            
            controller.enqueue(value);
        }
        }
    });

    // Return a new response with the tracked body
    return new Response(stream, {
        headers: response.headers,
        status: response.status,
        statusText: response.statusText
    });
}