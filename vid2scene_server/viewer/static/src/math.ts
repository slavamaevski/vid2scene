import * as nipplejs from 'nipplejs';
import * as THREE from 'three';

export function getJoystickDirection(joystick: nipplejs.Joystick): {
    x: number;
    y: number;
} {
    if (!joystick.options.size) {
        return {
            x: 0,
            y: 0
        };
    }

    const size = joystick.options.size / 2;
    const xFrontPosition = joystick.frontPosition.x;
    const yFrontPosition = joystick.frontPosition.y;


    return {
        x: xFrontPosition / size,
        y: -yFrontPosition / size
    };
}

export function getGroundForward(cameraForward: THREE.Vector3, cameraUp: THREE.Vector3): THREE.Vector3 {
    const groundForward = cameraForward.clone();
    groundForward.projectOnPlane(cameraUp);
    return groundForward.normalize();
}