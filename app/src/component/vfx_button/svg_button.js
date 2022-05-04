import React from 'react';
import {ReactComponent as FullscreenIcon} from '../../fullscreen-icon.svg';
import {ReactComponent as TileIcon} from '../../tile-icon.svg';
import {ReactComponent as FullscreenTileIcon} from '../../fullscreen-tile-icon.svg';
import {ReactComponent as SpiralIcon} from '../../spiral-icon.svg';

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
      case 'ANIMATION_MODE_FULLSCREEN':
        return <span className='position-relative'>
        <FullscreenIcon className={classes} aria-hidden='true' onClick={this.setAnimationMode} />
          <span className="icon-tooltip">Fullscreen</span></span>
      case 'ANIMATION_MODE_TILE':
        return <span className='position-relative'>
          <TileIcon className={classes} aria-hidden='true' onClick={this.setAnimationMode} />
          <span className="icon-tooltip">Tile</span></span>
      case 'ANIMATION_MODE_SPIRAL':
        return <span className='position-relative'>
          <SpiralIcon className={classes} aria-hidden='true' onClick={this.setAnimationMode} />
          <span className="icon-tooltip">Spiral</span></span>
      case 'ANIMATION_MODE_FULLSCREEN_TILE':
      default:
        return <span className='position-relative'>
          <FullscreenTileIcon className={classes} aria-hidden='true' onClick={this.setAnimationMode} />
          <span className="icon-tooltip">Alternate</span></span>
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
