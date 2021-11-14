import React from 'react';
import './vfx_button.css';
import tv_config from 'tv_config.json';

class VfxButton extends React.Component {
  constructor(props) {
    super(props);
    this.setAnimationMode = this.setAnimationMode.bind(this);
  }

  render() {
    const selected_class = this.isSelected() ? ' selected ' : '';
    return (
      <span className={this.props.button_class + selected_class + ' p-1 ml-3 mr-3 bg-light-text vfx-button'}
        aria-hidden='true'
        onClick={this.setAnimationMode} />
    );
  }

  setAnimationMode(e) {
    e.preventDefault();
    e.stopPropagation();
    const animation_mode = this.isSelected() ? 'ANIMATION_MODE_NONE' : this.props.button_animation_mode;
    this.props.setAnimationMode(animation_mode);
  }

  isSelected() {
    return this.props.button_animation_mode === this.props.app_animation_mode
  }

}

export default VfxButton;
