import React from 'react';
import {ReactComponent as TileIcon} from '../../tile-icon.svg';
import {ReactComponent as RepeatIcon} from '../../repeat-icon.svg';
import {ReactComponent as TileRepeatIcon} from '../../tile-repeat-icon.svg';

class SvgButton extends React.Component {
  constructor(props) {
    super(props);
    this.setAnimationMode = this.setAnimationMode.bind(this);
    this.renderButton = this.renderButton.bind(this);
  }

  renderButton() {
    const selected_class = this.isSelected() ? ' selected ' : '';
    const classes = 'svg-icon' + selected_class;
    switch(this.props.button_animation_mode) {
      case 'ANIMATION_MODE_TILE':
        return <span className='position-relative'>
        <TileIcon className={classes} aria-hidden='true' onClick={this.setAnimationMode} />
          <span class="icon-tooltip">Fullscreen</span></span>
      case 'ANIMATION_MODE_REPEAT':
        return <span className='position-relative'>
          <RepeatIcon className={classes} aria-hidden='true' onClick={this.setAnimationMode} />
          <span class="icon-tooltip">Tile</span></span>
      case 'ANIMATION_MODE_TILE_REPEAT':
        return <span className='position-relative'>
          <TileRepeatIcon className={classes} aria-hidden='true' onClick={this.setAnimationMode} />
          <span class="icon-tooltip">Alternate</span></span>
      case 'ANIMATION_MODE_SPIRAL': // TODO: change the spiral icon
        return <span className='position-relative'>
          <TileRepeatIcon className={classes} aria-hidden='true' onClick={this.setAnimationMode} />
          <span class="icon-tooltip">Spiral</span></span>
      default:
        return <TileRepeatIcon className={classes} aria-hidden='true'onClick={this.setAnimationMode} />
    }
  }

  render() {
    return (
      this.renderButton()
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

export default SvgButton;
