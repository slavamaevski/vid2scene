export interface Vector3 {
    x: number;
    y: number;
    z: number;
}

export type CameraType = 'orbital' | 'drone';

export interface CameraData {
    lookAt: Vector3;
    position: Vector3;
    up: Vector3;
    cameraType?: CameraType;
}

// Helper type for the parsed camera data used internally
export interface ParsedCameraData {
    initialCameraPosition: [number, number, number];
    initialCameraLookAt: [number, number, number];
    cameraUp: [number, number, number];
    useDroneControls: boolean;
} 