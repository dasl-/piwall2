import React from 'react';
import './vfx_button.css';
import tv_config from 'tv_config.json';

class VfxButton extends React.Component {
  constructor(props) {
    super(props);
    this.setAnimationMode = this.setAnimationMode.bind(this);
  }

  render() {
    let selected_class = '';
    if (this.props.button_animation_mode === this.props.app_animation_mode) {
      selected_class = ' selected '
    }
    return (
      <span className={this.props.button_class + selected_class + ' p-1 ml-3 mr-3 bg-light-text vfx-button'}
        aria-hidden='true'
        onClick={this.setAnimationMode} />
    );
  }

  setAnimationMode(e) {
    e.preventDefault();
    e.stopPropagation();
    this.props.setAnimationMode(this.props.button_animation_mode);
  }

}

export default VfxButton;
