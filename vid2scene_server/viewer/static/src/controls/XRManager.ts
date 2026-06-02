import * as pc from 'playcanvas';
import { PlayCanvasVRControls } from './PlayCanvasVRControls';

/**
 * Manager for WebXR sessions
 * Handles starting/ending VR sessions, camera setup, and VR controls
 */
export class XRManager {
    private app: pc.AppBase;
    private camera: pc.Entity;
    private vrControls: PlayCanvasVRControls | null = null;

    // Initial camera transform (to reset when entering VR)
    private initialPosition: pc.Vec3;
    private initialRotation: pc.Quat;

    // Pre-VR camera state (captured before starting VR)
    private preVRCameraPosition: pc.Vec3 | null = null;
    private preVRCameraForward: pc.Vec3 | null = null;

    // Callbacks
    private onStartCallback?: () => void;
    private onEndCallback?: () => void;

    constructor(
        app: pc.AppBase,
        camera: pc.Entity,
        initialPosition?: pc.Vec3,
        initialRotation?: pc.Quat
    ) {
        this.app = app;
        this.camera = camera;

        // Store initial transform or use current
        this.initialPosition = initialPosition || camera.getPosition().clone();
        this.initialRotation = initialRotation || camera.getRotation().clone();

        // Set up XR event listeners
        this.setupXRListeners();
    }

    /**
     * Check if WebXR VR is supported
     */
    static async isVRSupported(): Promise<boolean> {
        if (!navigator.xr) {
            return false;
        }
        try {
            return await navigator.xr.isSessionSupported('immersive-vr');
        } catch (e) {
            console.error('Error checking VR support:', e);
            return false;
        }
    }

    /**
     * Set up XR event listeners
     */
    private setupXRListeners() {
        this.app.xr.on('start', this.onXRStart);
        this.app.xr.on('end', this.onXREnd);
        this.app.xr.on('error', this.onXRError);
    }

    private onXRStart = () => {
        console.log('XR session started');

        // Create VR controls with pre-VR camera state
        this.vrControls = new PlayCanvasVRControls(
            this.app,
            this.camera,
            this.preVRCameraPosition!,
            this.preVRCameraForward!
        );

        // Trigger callback
        if (this.onStartCallback) {
            this.onStartCallback();
        }
    };

    private onXREnd = () => {
        console.log('XR session ended');

        // Cleanup VR controls
        if (this.vrControls) {
            this.vrControls.destroy();
            this.vrControls = null;
        }

        // Trigger callback
        if (this.onEndCallback) {
            this.onEndCallback();
        }
    };

    private onXRError = (error: Error) => {
        console.error('XR Error:', error);
    };

    /**
     * Start VR session
     */
    async startSession(): Promise<boolean> {
        try {
            // Check if XR is supported
            if (!this.app.xr.supported) {
                console.error('XR not supported on this device');
                return false;
            }

            // Check if VR is available
            if (!this.app.xr.isAvailable(pc.XRTYPE_VR)) {
                console.error('VR not available');
                return false;
            }

            // Don't reset camera position/rotation - let it stay where user left it
            // PlayCanvas XR will handle the camera setup automatically

            // Capture camera state BEFORE starting VR
            this.preVRCameraPosition = this.camera.getPosition().clone();
            this.preVRCameraForward = this.camera.forward.clone();

            console.log('Pre-VR camera position:', this.preVRCameraPosition.toString());
            console.log('Pre-VR camera forward:', this.preVRCameraForward.toString());

            // Start VR session with local reference space
            // pc.XRSPACE_LOCAL keeps the camera at its current position without adding floor offset
            // Pass the camera component, not the entity
            this.app.xr.start(this.camera.camera!, pc.XRTYPE_VR, pc.XRSPACE_LOCAL);

            return true;
        } catch (error) {
            console.error('Failed to start VR session:', error);
            return false;
        }
    }

    /**
     * End VR session
     */
    endSession() {
        if (this.app.xr.active) {
            this.app.xr.end();
        }
    }

    /**
     * Update VR controls (call this in app update loop)
     */
    update(dt: number) {
        if (this.vrControls && this.app.xr.active) {
            this.vrControls.update(dt);
        }
    }

    /**
     * Set callback for when XR session starts
     */
    onStart(callback: () => void) {
        this.onStartCallback = callback;
    }

    /**
     * Set callback for when XR session ends
     */
    onEnd(callback: () => void) {
        this.onEndCallback = callback;
    }

    /**
     * Check if currently in XR session
     */
    isActive(): boolean {
        return this.app.xr.active;
    }

    /**
     * Cleanup
     */
    destroy() {
        if (this.vrControls) {
            this.vrControls.destroy();
            this.vrControls = null;
        }

        this.app.xr.off('start', this.onXRStart);
        this.app.xr.off('end', this.onXREnd);
        this.app.xr.off('error', this.onXRError);
    }
}
