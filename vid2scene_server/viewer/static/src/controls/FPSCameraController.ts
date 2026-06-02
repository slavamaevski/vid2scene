import { getGroundForward } from '../math';
import { Object3D, Camera, Vector3, Quaternion } from 'three';


// Maximum camera pitch angle is PI/2 - MAX_PITCH_ANGLE_OFFSET_RADIANS radians
const MAX_PITCH_ANGLE_OFFSET_RADIANS = 0.6;
const PI_2 = Math.PI / 2;
const FLOAT_ZERO_THRESHOLD = 0.00001;
const _tempVector = new Vector3();



/**
 * A first-person camera controller that handles camera movement and rotation.
 * This controller provides methods for moving and rotating the camera in a first-person manner.
 * It handles arbitrary up vectors, which Three.js's default pointer lock controls do not.
*/
export class FPSCameraController {
	public cameraObject: Object3D;
	private _isLocked: boolean;

	/**
	 * Creates a new FPS camera controller
	 * @param camera - The Three.js camera to control
	 */
	constructor( camera: Camera ) {
		this.cameraObject = camera;
		this._isLocked = false;
	}

	/**
	 * Locks the camera controls, enabling movement and rotation
	 */
	lock() {
		this._isLocked = true;
	}

	/**
	 * Unlocks the camera controls, disabling movement and rotation
	 */
	unlock() {
		this._isLocked = false;
	}

	/**
	 * Gets the camera object being controlled
	 * @returns The camera object
	 */
	getObject() {

		return this.cameraObject;

	}

	/**
	 * Gets the current forward direction of the camera
	 * @param v - Vector3 to store the result in
	 * @returns The forward direction vector
	 */
	getDirection( v: Vector3 ): Vector3 {

		return v.set( 0, 0, - 1 ).applyQuaternion( this.cameraObject.quaternion );

	}

	/**
	 * Moves the camera forward along its current direction projected onto the xz-plane
	 * @param distance - Distance to move forward
	 */
	moveForward( distance: number ): void {

		if ( this._isLocked === false ) return;

		// Move forward parallel to the xz-plane
		const camera = this.cameraObject;

		// Get the camera's forward direction (negative z-axis in camera space)
		_tempVector.set( 0, 0, - 1 ).applyQuaternion( camera.quaternion );

		camera.position.addScaledVector( _tempVector, distance );

	}

	/**
	 * Moves the camera right relative to its current orientation
	 * @param distance - Distance to move right (negative for left)
	 */
	moveRight( distance: number ): void {

		if ( this._isLocked === false ) return;

		const camera = this.cameraObject;

		// Get the camera's right direction (x-axis in camera space)
		_tempVector.set( 1, 0, 0 ).applyQuaternion( camera.quaternion );

		camera.position.addScaledVector( _tempVector, distance );

	}

    /**
     * Moves the camera up relative to its current orientation
     * @param distance - Distance to move up (negative for down)
     */
    moveUp(distance: number): void {
        if (this._isLocked === false) return;

        const camera = this.cameraObject;

        // Get the camera's up direction (y-axis in camera space)
        _tempVector.set(0, 1, 0).applyQuaternion(camera.quaternion);

        camera.position.addScaledVector(_tempVector, distance);
    }

    roll(angle: number): void {
        this.cameraObject.rotateZ(-angle);
    }

	/**
	 * Applies pitch and yaw rotations to the camera while maintaining proper orientation
	 * and respecting pitch limits
	 * @param pitchChange - Amount to change pitch in radians (positive is down)
	 * @param yawChange - Amount to change yaw in radians (positive is counterclockwise)
	 */
	applyRotation(pitchChange: number, yawChange: number, worldUp: Vector3): void {

		if (this._isLocked === false) return;

        const camera = this.cameraObject;
        camera.up = camera.up.clone().normalize();
        
        // --- Yaw (Horizontal Rotation) ---

        // Calculate the yaw angle based on mouse movement
        const yawAngle = yawChange;

        // Create a quaternion representing the yaw rotation around the world up axis
        const yawQuaternion = new Quaternion().setFromAxisAngle(worldUp, yawAngle);

        // Apply the yaw rotation to the camera's current orientation
        camera.quaternion.premultiply(yawQuaternion);

        // --- Pitch (Vertical Rotation) ---

        // Calculate the desired pitch change based on mouse movement
        const desiredPitchChange = pitchChange;

        // Clone the camera to test the potential pitch rotation
        const right = new Vector3(1, 0, 0).applyQuaternion(camera.quaternion).normalize();

        // Define pitch limits in radians
        const minPitch = -PI_2 + MAX_PITCH_ANGLE_OFFSET_RADIANS;
        const maxPitch = PI_2 - MAX_PITCH_ANGLE_OFFSET_RADIANS;

        // Calculate current pitch before applying the change
        const currentForward = camera.getWorldDirection(new Vector3()).clone().normalize();
        const currentGroundForward = getGroundForward(currentForward, camera.up);

        const currentPitch = Math.sign(currentForward.dot(camera.up)) * currentGroundForward.angleTo(currentForward);

        // Calculate the desired new pitch
        const newDesiredPitch = currentPitch - desiredPitchChange;
        
        // Clamp the new pitch within the defined limits
        const clampedDesiredPitch = Math.max(minPitch, Math.min(maxPitch, newDesiredPitch));
        
		// Calculate the actual pitch change after clamping
        const clampedPitchChange = clampedDesiredPitch - currentPitch;
		if (Math.abs(clampedPitchChange) > FLOAT_ZERO_THRESHOLD) {
			const adjustedPitchQuaternion = new Quaternion().setFromAxisAngle(right, clampedPitchChange);
			camera.quaternion.premultiply(adjustedPitchQuaternion);
		}
	}
}
