// AutoLOD Web Worker
// Runs Emscripten module in a Worker context to enable WORKERFS

let Module = null;
let processingDone = false;  // Global flag

// Get base URL for loading scripts
const baseUrl = self.location.href.replace(/\/[^\/]*$/, '/');

// Import the Emscripten module
importScripts(baseUrl + '3dgs_autolod.js');

// Track which LOD files we've already sent
let sentFiles = new Set();

// Send a LOD file to main thread
function sendLodFile(lodPath) {
    if (sentFiles.has(lodPath)) return;
    sentFiles.add(lodPath);

    try {
        const data = Module.FS.readFile(lodPath);
        const fname = lodPath.split('/').pop();
        // Transfer ownership of buffer for efficiency
        self.postMessage(
            { type: 'lodReady', name: fname, data: data },
            [data.buffer]
        );
        // Clean up the file from MEMFS to save memory
        Module.FS.unlink(lodPath);
        self.postMessage({ type: 'print', text: `📥 ${fname} ready for download` });
    } catch (err) {
        self.postMessage({ type: 'printErr', text: 'Failed to read LOD: ' + err.message });
    }
}

// Handle messages from main thread
self.onmessage = async function (e) {
    const { type, file, args } = e.data;

    if (type === 'init') {
        try {
            Module = await AutoLOD({
                mainScriptUrlOrBlob: baseUrl + '3dgs_autolod.js',
                locateFile: function (path, prefix) {
                    // Return absolute URLs for all files
                    if (path.endsWith('.wasm')) return baseUrl + '3dgs_autolod.wasm';
                    if (path.endsWith('.worker.js')) return baseUrl + '3dgs_autolod.js';
                    return baseUrl + path;
                },
                print: function (text) {
                    self.postMessage({ type: 'print', text: text });

                    // Detect "Saving checkpoint: /path.ply... done" pattern
                    const checkpointMatch = text.match(/Saving checkpoint: (\/[^\s]+\.ply)\.\.\. done/);
                    if (checkpointMatch) {
                        sendLodFile(checkpointMatch[1]);
                    }

                    // Also detect final save: "Saving final (N) to /path.ply..."
                    // The file is done when we see "Done!" after this
                    const finalMatch = text.match(/Saving final \(\d+\) to (\/[^\s]+\.ply)/);
                    if (finalMatch) {
                        // Store path for when Done! is detected
                        Module._pendingFinalPath = finalMatch[1];
                    }

                    // Check for Done! to signal completion
                    if (text && text.includes('Done!')) {
                        // Send final LOD if pending
                        if (Module._pendingFinalPath) {
                            sendLodFile(Module._pendingFinalPath);
                            Module._pendingFinalPath = null;
                        }
                        processingDone = true;
                    }
                },
                printErr: function (text) {
                    self.postMessage({ type: 'printErr', text: text });
                }
            });
            self.postMessage({ type: 'ready' });
        } catch (err) {
            self.postMessage({ type: 'error', message: 'Failed to init WASM: ' + err.message });
        }
        return;
    }

    if (type === 'process') {
        if (!Module) {
            self.postMessage({ type: 'error', message: 'Module not initialized' });
            return;
        }

        try {
            // Reset state
            sentFiles.clear();
            processingDone = false;
            Module._pendingFinalPath = null;

            // Mount WORKERFS
            try { Module.FS.unmount('/work'); } catch (e) { }
            try { Module.FS.mkdir('/work'); } catch (e) { }

            Module.FS.mount(Module.WORKERFS, { files: [file] }, '/work');
            const inputPath = '/work/' + file.name;

            self.postMessage({ type: 'print', text: `File mounted: ${inputPath} (${(file.size / 1024 / 1024).toFixed(2)} MB)` });

            // Build full args array
            const fullArgs = [inputPath, '/output.ply', ...args];
            self.postMessage({ type: 'print', text: `Executing: 3dgs-autolod ${fullArgs.join(' ')}` });

            // Run (may be async with pthreads)
            Module.callMain(fullArgs);

            // Wait for "Done!" to be detected in the print callback
            while (!processingDone) {
                await new Promise(r => setTimeout(r, 100));
            }

            // Cleanup
            try { Module.FS.unlink('/output.ply'); } catch (e) { }
            try { Module.FS.unmount('/work'); } catch (e) { }

            // Signal completion
            self.postMessage({ type: 'done', results: [] });

        } catch (err) {
            self.postMessage({ type: 'error', message: err.message || String(err) });
        }
    }
};
