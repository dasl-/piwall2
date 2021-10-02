import React from 'react';
import api from 'api';

class TV extends React.Component {

  constructor(props) {
    super(props);

    this.apiClient = new api();

    this.state = {};
  }

  render() {
    let props = this.props;
    let src = props.src;
    let scale = props.scale;
    let bgPos = "-" + ((props.x * scale) + props.offsetX) + "px -" + ((props.y * scale) + props.offsetY) + "px";

    return (
      <div className='tv' style={
        {
          top:(props.y * scale),
          left:(props.x * scale),
          width:props.width * scale,
          height:props.height * scale,
          backgroundImage: `url(${src})`,
          backgroundPosition: bgPos
        }
        }>
      </div>
    );
  }
}

export default TV;