import Shepherd from 'shepherd.js';
import type { Tour, StepOptions } from 'shepherd.js';
import pinchIcon from '../assets/pinch.svg';
import dragIcon from '../assets/touch_drag_2.svg';

interface ViewerTourConfig {
  isMobile: boolean;
  isDroneMode: boolean;
}

function getCommonSteps(isMobile: boolean): StepOptions[] {
  return [
    {
      id: 'welcome',
      text: 'Welcome to the vid2scene 3D Scene Viewer! Let\'s take a quick tour to help you explore this 3D scene.',
      buttons: [{
        text: 'Next',
        action: function() { this.next(); },
        classes: 'shepherd-button-primary'
      }]
    },
    {
      id: 'settings',
      text: `${isMobile ? 'Tap' : 'Click'} the gear icon to access the settings menu and view detailed control instructions. Scene owners can also save their preferred starting camera position and orientation here.`,
      attachTo: {
        element: '.menu-button',
        on: 'bottom'
      },
      buttons: [
        {
          text: 'Previous',
          action: function() { this.back(); },
          classes: 'shepherd-button-secondary'
        },
        {
          text: 'Next',
          action: function() { this.next(); },
          classes: 'shepherd-button-primary'
        }
      ]
    },
    {
      id: 'controls',
      text: 'This button switches between the two viewing modes:<br><br>• Drone Mode: Move freely like flying a drone.<br>• Orbital Mode: Rotate around a fixed object in 3D space',
      attachTo: {
        element: '#controlsButton',
        on: 'top'
      },
      buttons: [
        {
          text: 'Previous',
          action: function() { this.back(); },
          classes: 'shepherd-button-secondary'
        },
        {
          text: 'Next',
          action: function() { this.next(); },
          classes: 'shepherd-button-primary'
        }
      ]
    }
  ];
}

function getNormalStepButtons(): StepOptions['buttons'] {
  return [
    {
      text: 'Previous',
      action: function() { this.back(); },
      classes: 'shepherd-button-secondary'
    },
    {
      text: 'Next',
      action: function() { this.next(); },
      classes: 'shepherd-button-primary'
    }
  ];
}

function getFinalStepButtons(): StepOptions['buttons'] {
  return [
    {
      text: 'Previous',
      action: function() { this.back(); },
      classes: 'shepherd-button-secondary'
    },
    {
      text: 'Start Exploring',
      action: function() { this.complete(); },
      classes: 'shepherd-button-primary shepherd-button-complete'
    }
  ];
}

function getMobileOrbitalSteps(): StepOptions[] {
  return [
    {
      id: 'orbital-controls',
      text: `<div style="text-align: center;">
        Use touch gestures to navigate the environment:<br><br>
        <div style="display: flex; justify-content: center; gap: 32px; margin-bottom: 10px;">
          <div style="width: 150px;">
            <img src="${pinchIcon}" alt="Pinch gesture" style="width: 96px; height: 96px;"><br>
            <span>Pinch to zoom in and out</span>
          </div>
          <div style="width: 150px;">
            <img src="${dragIcon}" alt="Drag gesture" style="width: 96px; height: 96px;"><br>
            <span>Touch and drag to orbit around the scene</span>
          </div>
        </div>
        <br>
        Also, you can tap on objects to focus on them.
      </div>`,
      buttons: getNormalStepButtons()
    },
    {
      id: 'orbital-done',
      text: 'Pro tip: Check the settings menu for the complete control instructions. <br><br>Happy viewing!',
      buttons: getFinalStepButtons()
    }
  ];
}

function getMobileDroneSteps(): StepOptions[] {
  return [
    {
      id: 'joystick-left',
      text: 'Use this joystick to move around:<br><br>• Up/Down: Move forward/backward<br>• Left/Right: Move sideways',
      attachTo: {
        element: '#movement-joystick-position-zone',
        on: 'bottom'
      },
      buttons: [
        {
          text: 'Previous',
          action: function() { this.back(); },
          classes: 'shepherd-button-secondary'
        },
        {
          text: 'Next',
          action: function() { this.next(); },
          classes: 'shepherd-button-primary'
        }
      ]
    },
    {
      id: 'joystick-right',
      text: 'This joystick controls where you look:<br><br>• Move in any direction to rotate the camera',
      attachTo: {
        element: '#rotation-joystick-position-zone',
        on: 'bottom'
      },
      buttons: [
        {
          text: 'Previous',
          action: function() { this.back(); },
          classes: 'shepherd-button-secondary'
        },
        {
          text: 'Next',
          action: function() { this.next(); },
          classes: 'shepherd-button-primary'
        }
      ]
    },
    {
      id: 'touch-gestures',
      text: `<div style="text-align: center;">
        You can also use touch gestures:<br><br>
        <div style="display: flex; justify-content: center; gap: 32px; margin-bottom: 10px;">
          <div style="width: 150px;">
            <img src="${pinchIcon}" alt="Pinch gesture" style="width: 96px; height: 96px;"><br>
            <span>Pinch to move forward and backward</span>
          </div>
          <div style="width: 150px;">
            <img src="${dragIcon}" alt="Drag gesture" style="width: 96px; height: 96px;"><br>
            <span>Touch and drag to look around</span>
          </div>
        </div>
      </div>`,
      buttons: getFinalStepButtons()
    },
    {
      id: 'joystick-done',
      text: 'Pro tip: Check the settings menu for the complete control instructions. <br><br>Happy viewing!',
      buttons: getFinalStepButtons()
    }
  ];
}

function getDesktopDroneSteps(): StepOptions[] {
  return [
    {
      id: 'desktop-drone-controls',
      text: 'Right now, you are in drone mode. Left click and drag to look around. Right click to move camera forward.',
      buttons: getNormalStepButtons()
    },
    {
      id: 'done',
      text: 'Pro tip: You can also use the middle mouse button or WASD keys to control the camera. Check the settings menu for the complete control instructions. <br><br>Happy viewing!',
      buttons: getFinalStepButtons()
    }
  ];
}

function getDesktopOrbitalSteps(): StepOptions[] {
  return [
    {
      id: 'desktop-orbital-controls',
      text: 'Right now, you are in orbital mode. Left click something in the scene to focus on it. Left click and drag to orbit the camera. Right click to pan the camera.',
      buttons: getNormalStepButtons()
    },
    {
      id: 'done',
      text: 'Pro tip: You can also use the middle mouse button or WASD keys to control the camera. Check the settings menu for the complete control instructions. <br><br>Happy viewing!',
      buttons: getFinalStepButtons()
    }
  ];
}

export function createTour({ isMobile, isDroneMode }: ViewerTourConfig): Tour {
  const tour = new Shepherd.Tour({
    useModalOverlay: true,
    defaultStepOptions: {
      classes: 'shepherd-theme-bootstrap',
      scrollTo: true,
      cancelIcon: {
        enabled: true
      }
    }
  });

  const modeSpecificSteps = isMobile
    ? (isDroneMode ? getMobileDroneSteps() : getMobileOrbitalSteps())
    : (isDroneMode ? getDesktopDroneSteps() : getDesktopOrbitalSteps());

  const steps = [...getCommonSteps(isMobile), ...modeSpecificSteps];
  
  steps.forEach(step => tour.addStep(step));
  
  tour.on('complete', () => {
    localStorage.setItem('hasSeenVid2SceneTour', 'true');
  });

  return tour;
} 