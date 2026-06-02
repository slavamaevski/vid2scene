export function getUnmaskedRenderer(): string | undefined {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl');
    if (!gl) {
        return undefined;
    }
    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
    if (!debugInfo) {
        return undefined;
    }
    const renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
    if (!renderer) {
        return undefined;
    }
    return renderer as string;
}

export function shouldIgnoreDevicePixelRatio(): boolean {
    try {
        const renderer = getUnmaskedRenderer();
        if (!renderer) {
        return false;
        }

        const lowerRenderer = renderer.toLowerCase();
        return lowerRenderer.includes('intel') || lowerRenderer.includes('swiftshader');
    } catch (e) {
        return false;
    }
}

