import * as pc from "playcanvas";

// LOD preset definitions: control quality/performance tradeoff
// range: [min, max] LOD levels (0=highest detail, 5=lowest)
// lodDistances: distance thresholds for switching between LOD levels
// splatBudget: max number of splats to render at once
export const LOD_PRESETS: Record<
    string,
    {
        range: [number, number];
        lodDistances: number[];
        splatBudget: number;
    }
> = {
    "desktop-max": {
        range: [0, 5],
        lodDistances: [10, 20, 50, 100, 200],
        splatBudget: 1500000,
    },
    desktop: {
        range: [0, 5],
        lodDistances: [10, 25, 60, 150, 250],
        splatBudget: 1000000,
    },
    "mobile-max": {
        range: [0, 5],
        lodDistances: [8, 20, 50, 120, 200],
        splatBudget: 750000,
    },
    mobile: {
        range: [0, 5],
        lodDistances: [3, 10, 30, 80, 150],
        splatBudget: 500000,
    },
};

/**
 * Configure PlayCanvas LOD scene settings for octree streaming.
 * Must be called after the gsplat component is added.
 */
export function configureLodScene(app: pc.Application): void {
    if (!app.scene.gsplat) {
        console.warn("app.scene.gsplat not available — LOD settings not applied");
        return;
    }

    // Core LOD streaming settings
    app.scene.gsplat.lodUpdateAngle = 90;
    app.scene.gsplat.lodBehindPenalty = 2;
    app.scene.gsplat.radialSorting = true;
    app.scene.gsplat.lodUpdateDistance = 1;
    app.scene.gsplat.lodUnderfillLimit = 10;

    // SH color update parameters
    app.scene.gsplat.colorUpdateDistance = 1;
    app.scene.gsplat.colorUpdateAngle = 4;
    app.scene.gsplat.colorUpdateDistanceLodScale = 2;
    app.scene.gsplat.colorUpdateAngleLodScale = 2;
}

/**
 * Apply a LOD preset to the scene and gsplat entity.
 */
export function applyLodPreset(
    app: pc.Application,
    gsEntity: pc.Entity,
    presetName: string,
): void {
    const preset = LOD_PRESETS[presetName] || LOD_PRESETS.desktop;

    if (app.scene.gsplat) {
        app.scene.gsplat.lodRangeMin = preset.range[0];
        app.scene.gsplat.lodRangeMax = preset.range[1];
    }

    const gs = gsEntity.gsplat;
    if (gs) {
        gs.lodDistances = preset.lodDistances;
        (gs as any).splatBudget = preset.splatBudget;
    }
}

/**
 * Detect whether we should use the mobile preset.
 */
export function isMobileDevice(): boolean {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
        navigator.userAgent,
    );
}

/**
 * Load a LOD gsplat asset from Azure Blob Storage using per-blob SAS URLs.
 *
 * Fetches a map of {relativePath: {url, size}} from the backend (same format
 * as sog_urls), creates a PlayCanvas gsplat asset pointing to the lod-meta.json
 * SAS URL, and uses mapUrl to resolve each chunk filename to its pre-signed URL.
 *
 * @param app - PlayCanvas Application instance
 * @param sasUrls - Map of relative paths to SAS URLs and sizes
 * @param spjId - Unique identifier for the current scene/project, used for virtual URL mapping
 * @param onProgress - Optional progress callback
 * @returns The loaded PlayCanvas asset
 */
export async function loadLodAsPlayCanvasAsset(
    app: any,
    gsEntity: any,
    sasUrls: Record<string, any>,
    spjId: string,
    onProgress?: (step: string, progress: number) => void
) {
    // 1. Send SAS Map to Service Worker
    if ('serviceWorker' in navigator) {
        // Ensure SW is controlling the page
        if (!navigator.serviceWorker.controller) {
            console.log("Waiting for Service Worker controller...");
            await new Promise<void>(resolve => {
                const onControllerChange = () => {
                    navigator.serviceWorker.removeEventListener('controllerchange', onControllerChange);
                    resolve();
                };
                navigator.serviceWorker.addEventListener('controllerchange', onControllerChange);
                // Fallback timeout in case it takes too long or never claims (3s)
                setTimeout(() => {
                    navigator.serviceWorker.removeEventListener('controllerchange', onControllerChange);
                    resolve();
                }, 3000);
            });
        }

        if (navigator.serviceWorker.controller) {
            console.log("Sending SAS URLs to Service Worker for scene:", spjId);
            navigator.serviceWorker.controller.postMessage({
                type: 'SET_SAS_URLS',
                spjId: spjId,
                sasUrls: sasUrls
            });
        } else {
            console.warn("Service Worker not controlling page! LOD loading might fail or use wrong URLs.");
        }
    }

    // 2. Initialize Asset with Virtual URL
    // The Service Worker will intercept requests to /virtual/lod/<spjId>/...
    // and redirect them to the SAS URLs provided above.
    const virtualBaseUrl = `/virtual/lod/${spjId}/`;
    const assetUrl = virtualBaseUrl + "lod-meta.json";

    const asset = new pc.Asset("gs-lod", "gsplat", {
        url: assetUrl,
        filename: "lod-meta.json",
    }, {});

    return new Promise<pc.Asset>((resolve, reject) => {
        asset.once("load", (asset: pc.Asset) => {
            resolve(asset);
        });
        asset.once("error", (err: string) => {
            reject(new Error(err));
        });

        // Add to registry and load
        app.assets.add(asset);
        app.assets.load(asset);
    }).then((loadedAsset: any) => {
        // Add gsplat component with unified rendering (required for LOD octree).
        // IMPORTANT: The `unified` setter rejects changes when the component is enabled.
        // We must temporarily disable the entity so that `unified: true` is accepted
        // during component initialization; otherwise it silently falls back to the
        // non-unified GSplatInstance path which crashes on octree resources.

        gsEntity.enabled = false;
        // Clean up existing component if any?
        if (gsEntity.components && gsEntity.components.gsplat) {
            gsEntity.removeComponent("gsplat");
        }

        gsEntity.addComponent("gsplat", {
            asset: loadedAsset.id,
            unified: true,
        });
        gsEntity.enabled = true;

        // Configure LOD scene settings and apply device-appropriate preset
        configureLodScene(app);
        applyLodPreset(app, gsEntity, "desktop-max");

        // Wait for initial splats to render so we don't show a blank screen
        // Wait for splats to render so we don't show a blank screen
        // Target 750k splats for a "full enough" scene
        return new Promise<any>((resolve) => {
            let attempts = 0;
            const maxAttempts = 100; // 20 seconds at 100ms interval
            const targetSplatCount = 1_250_000;

            const checkRender = setInterval(() => {
                attempts++;

                const currentSplats = app.stats?.frame?.gsplats || 0;
                // Update progress: 0 to 100% based on target
                const progress = Math.min((currentSplats / targetSplatCount) * 100, 100);
                onProgress?.("Loading", progress);

                // Check if we hit target
                if (currentSplats >= targetSplatCount) {
                    clearInterval(checkRender);
                    resolve(loadedAsset);
                    return;
                }

                if (attempts >= maxAttempts) {
                    console.warn("Timeout waiting for target LOD render - proceeding anyway");
                    clearInterval(checkRender);
                    resolve(loadedAsset);
                }
            }, 200);
        });
    });
}
