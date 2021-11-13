import React from 'react';
import './vfx_button.css';
import tv_config from 'tv_config.json';

class VfxButton extends React.Component {
  constructor(props) {
    super(props);
    this.clickHandler = this.clickHandler.bind(this);
  }

  render() {
    return (
      <span className={this.props.button_class + ' bg-light-text vfx-button'}
        aria-hidden='true'
        onClick={this.clickHandler} />
    );
  }

  clickHandler(e) {
    e.preventDefault();
    e.stopPropagation();
    if (this.props.animation_mode) {
      this.setAnimationMode();
    } else {
      this.setDisplayMode();
    }
  }

  setAnimationMode() {
    this.props.setAnimationMode(this.props.animation_mode);
  }

  setDisplayMode() {
    var display_mode_by_tv_id = {}
    for (const tv_id in tv_config['tvs']) {
      display_mode_by_tv_id[tv_id] = this.props.display_mode;
    }
    this.props.setDisplayMode(display_mode_by_tv_id);
  }

}

export default VfxButton;
