import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { DemoTag } from '../../components/demo-tag/demo-tag.component';
import { NavigationLink } from '../../components/navigation-link/navigation-link.component';

@Component({
  selector: 'app-demo-landing',
  imports: [RouterLink, DemoTag, NavigationLink],
  templateUrl: './demo-landing.component.html',
  styleUrl: './demo-landing.component.scss',
})
export class DemoLanding {}
